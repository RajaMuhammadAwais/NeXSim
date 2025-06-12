# /home/ubuntu/modern_simulator/kernel/kernel_service.py

import grpc
import time
from concurrent import futures
import logging
import sys
import heapq # For priority queue (event list)
import json
import uuid
from google.protobuf.any_pb2 import Any

# Add proto directory to path to import generated code
sys.path.append("/home/ubuntu/modern_simulator/proto")

# Import generated gRPC files
import kernel_pb2
import kernel_pb2_grpc
import runtime_pb2
import runtime_pb2_grpc
import shared_messages_pb2  # Import shared message definitions
import model_messages_pb2 # For creating initial START event

# Basic logging configuration - SET TO DEBUG
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

# In-memory storage for simulation instances (for MVP)
# Key: kernel_instance_id, Value: dict containing state
simulation_instances = {}

# Runtime service connection details (assuming one runtime for MVP)
RUNTIME_SERVICE_ADDRESS = "localhost:50053"

class KernelServiceServicer(kernel_pb2_grpc.KernelServiceServicer):
    """Provides methods that implement functionality of the kernel server."""

    def _get_runtime_stub(self):
        """Creates a gRPC stub for the Runtime service."""
        channel = grpc.insecure_channel(RUNTIME_SERVICE_ADDRESS)
        return runtime_pb2_grpc.RuntimeServiceStub(channel)

    def InitializeSimulation(self, request, context):
        """Handles request to initialize a simulation instance."""
        sim_id = request.simulation_id
        kernel_id = request.kernel_instance_id
        logging.info(f"Received InitializeSimulation request for sim_id: {sim_id}, kernel_id: {kernel_id}")

        if kernel_id in simulation_instances:
            logging.warning(f"Kernel instance ID {kernel_id} already exists.")
            return kernel_pb2.InitializeSimulationResponse(
                simulation_id=sim_id,
                kernel_instance_id=kernel_id,
                success=False,
                message=f"Kernel instance ID {kernel_id} already exists."
            )

        instance = {
            "simulation_id": sim_id,
            "status": "INITIALIZING",
            "current_time": 0.0,
            "event_queue": [],
            "next_event_id": 0,
            "scenario_config_raw": request.scenario_config,
            "scenario_config": None,
            "models": {},
            "runtime_stubs": {RUNTIME_SERVICE_ADDRESS: self._get_runtime_stub()}
        }
        simulation_instances[kernel_id] = instance

        try:
            # Parse scenario config
            logging.info(f"Parsing scenario config for {kernel_id}")
            instance["scenario_config"] = json.loads(request.scenario_config)
            logging.info(f"Successfully parsed scenario config for {kernel_id}")
            logging.debug(f"Scenario config: {json.dumps(instance['scenario_config'], indent=2)}")
            
            # Log nodes and initial events
            nodes = instance["scenario_config"].get("nodes", [])
            initial_events = instance["scenario_config"].get("initial_events", [])
            logging.info(f"Scenario contains {len(nodes)} nodes and {len(initial_events)} initial events")
            
            # Load models
            runtime_stub = instance["runtime_stubs"][RUNTIME_SERVICE_ADDRESS]
            load_success = True
            for node_config in nodes:
                model_id = node_config["model_id"]
                model_type = node_config["model_type"]
                model_specific_config = json.dumps(node_config.get("config", {}))
                instance["models"][model_id] = {"type": model_type, "runtime": RUNTIME_SERVICE_ADDRESS}
                logging.info(f"Loading model {model_id} of type {model_type}")

                # Use shared_messages_pb2 for LoadModelRequest
                load_req = shared_messages_pb2.LoadModelRequest(
                    simulation_id=sim_id,
                    model_id=model_id,
                    model_type=model_type,
                    model_config=model_specific_config
                )
                logging.info(f"Calling Runtime LoadModel for model_id: {model_id}")
                load_resp = runtime_stub.LoadModel(load_req)
                logging.info(f"LoadModel response for {model_id}: success={load_resp.success}, message={load_resp.message}")
                
                if not load_resp.success:
                    logging.error(f"Failed to load model {model_id} on runtime: {load_resp.message}")
                    load_success = False
                    break

            if not load_success:
                 instance["status"] = "FAILED"
                 return kernel_pb2.InitializeSimulationResponse(
                     simulation_id=sim_id, kernel_instance_id=kernel_id, success=False,
                     message="Failed to load one or more models."
                 )

            # Schedule initial events
            logging.info(f"Scheduling {len(initial_events)} initial events for {kernel_id}...")
            for event_config in initial_events:
                 start_any = Any()
                 event_type = event_config["event_type"]
                 # Construct the type URL based on the event_type from the scenario
                 start_any.type_url = f"type.googleapis.com/modern.proto.models.{event_type}Signal"
                 logging.info(f"Creating initial event with type_url: {start_any.type_url}")
                 
                 timestamp = event_config["timestamp"]
                 target_model_id = event_config["target_model_id"]
                 logging.info(f"Initial event details: time={timestamp}, target={target_model_id}, type={event_type}")

                 # Use shared_messages_pb2 for SimulationEvent
                 initial_event = shared_messages_pb2.SimulationEvent(
                     timestamp=timestamp,
                     target_model_id=target_model_id,
                     source_model_id="KERNEL_INIT",
                     event_data=start_any
                 )
                 
                 # Schedule the event
                 success = self._schedule_event(instance, initial_event)
                 if success:
                     logging.info(f"Successfully scheduled initial event for {target_model_id} at time {timestamp}")
                 else:
                     logging.error(f"Failed to schedule initial event for {target_model_id}")
            
            # Log event queue state
            logging.info(f"Initial event queue for {kernel_id}: {instance['event_queue']}")
            if instance['event_queue']:
                next_event_time, _, next_event = instance['event_queue'][0]
                logging.info(f"Next event scheduled at time {next_event_time} for {next_event.target_model_id}")
            else:
                logging.warning(f"Event queue is empty after initialization for {kernel_id}")

            instance["status"] = "INITIALIZED"
            logging.info(f"Kernel instance {kernel_id} for simulation {sim_id} initialized successfully.")
            return kernel_pb2.InitializeSimulationResponse(
                simulation_id=sim_id,
                kernel_instance_id=kernel_id,
                success=True,
                message=f"Kernel instance {kernel_id} initialized successfully."
            )

        except json.JSONDecodeError as e:
            instance["status"] = "FAILED"
            error_msg = f"Failed to parse scenario config for {kernel_id}: {e}"
            logging.error(error_msg)
            return kernel_pb2.InitializeSimulationResponse(simulation_id=sim_id, kernel_instance_id=kernel_id, success=False, message=error_msg)
        except grpc.RpcError as e:
            instance["status"] = "FAILED"
            error_msg = f"gRPC error during initialization of {kernel_id}: {e.code()} - {e.details()}"
            logging.error(error_msg)
            return kernel_pb2.InitializeSimulationResponse(simulation_id=sim_id, kernel_instance_id=kernel_id, success=False, message=error_msg)
        except Exception as e:
            instance["status"] = "FAILED"
            error_msg = f"Unexpected error initializing {kernel_id}: {e}"
            logging.error(error_msg, exc_info=True)
            return kernel_pb2.InitializeSimulationResponse(simulation_id=sim_id, kernel_instance_id=kernel_id, success=False, message=error_msg)

    def _schedule_event(self, instance, event, internal_event=True):
        """Helper method to schedule an event in the simulation instance."""
        try:
            if not event.event_id:
                event.event_id = f"evt-{instance['next_event_id']}"
                instance['next_event_id'] += 1
            
            # Add to priority queue (timestamp, event_id for tiebreaker, event)
            heapq.heappush(instance["event_queue"], (event.timestamp, event.event_id, event))
            logging.debug(f"Scheduled event {event.event_id} for time {event.timestamp}, target={event.target_model_id}")
            return True
        except Exception as e:
            logging.error(f"Error scheduling event: {e}", exc_info=True)
            return False

    def RunSimulationStep(self, request, context):
        """Handles request to run the simulation forward in time."""
        sim_id = request.simulation_id
        kernel_id = request.kernel_instance_id
        run_until = request.run_until_time
        logging.info(f"Received RunSimulationStep request for kernel_id: {kernel_id}, run until: {run_until}")

        if kernel_id not in simulation_instances:
            logging.warning(f"Kernel instance ID {kernel_id} not found.")
            return kernel_pb2.RunSimulationStepResponse(
                simulation_id=sim_id, kernel_instance_id=kernel_id, success=False,
                message=f"Kernel instance ID {kernel_id} not found."
            )

        instance = simulation_instances[kernel_id]
        inst_status = instance["status"]
        inst_time = instance["current_time"]

        if inst_status not in ["INITIALIZED", "RUNNING", "PAUSED"]:
             logging.warning(f"Kernel instance {kernel_id} is not in a runnable state ({inst_status}).")
             return kernel_pb2.RunSimulationStepResponse(
                simulation_id=sim_id, kernel_instance_id=kernel_id,
                current_simulation_time=inst_time, success=False, completed=False,
                message=f"Kernel instance {kernel_id} not runnable (status: {inst_status})."
            )

        instance["status"] = "RUNNING"
        completed = False
        processed_events = 0
        runtime_error = False

        logging.info(f"Starting RunSimulationStep loop for {kernel_id}. Current time: {inst_time}. Event queue size: {len(instance['event_queue'])}")
        
        # Check if event queue is empty
        if not instance["event_queue"]:
            logging.warning(f"Event queue is empty for {kernel_id}. No events to process.")
            instance["status"] = "PAUSED"
            return kernel_pb2.RunSimulationStepResponse(
                simulation_id=sim_id,
                kernel_instance_id=kernel_id,
                current_simulation_time=inst_time,
                completed=False,
                success=True,
                message=f"No events to process. Simulation paused at time {inst_time}."
            )
        
        # Basic DES loop
        while instance["event_queue"]:
            logging.info(f"Event queue before pop: {instance['event_queue']}")
            event_time, _, event = heapq.heappop(instance["event_queue"])
            current_inst_time = instance["current_time"]
            logging.info(f"Popped event {event.event_id} with time {event_time}. Current sim time: {current_inst_time}")

            if event_time > run_until:
                heapq.heappush(instance["event_queue"], (event_time, event.event_id, event))
                logging.info(f"Stopping run at time {current_inst_time}. Next event at {event_time} > {run_until}. Pushed event back.")
                break

            if event_time < current_inst_time:
                logging.error(f"Error: Event {event.event_id} time {event_time} is less than current time {current_inst_time}. Skipping.")
                continue

            instance["current_time"] = event_time
            logging.info(f"Advanced simulation time to {event_time}. Processing event {event.event_id} for model {event.target_model_id}")

            target_model_id = event.target_model_id
            if target_model_id not in instance["models"]:
                logging.warning(f"Target model {target_model_id} for event {event.event_id} not found in kernel instance {kernel_id}. Skipping.")
                continue

            model_info = instance["models"][target_model_id]
            runtime_addr = model_info["runtime"]
            if runtime_addr not in instance["runtime_stubs"]:
                 logging.error(f"Runtime address {runtime_addr} not found for model {target_model_id}. Cannot process event {event.event_id}. Bailing out.")
                 runtime_error = True
                 break

            runtime_stub = instance["runtime_stubs"][runtime_addr]

            try:
                # Use shared_messages_pb2 for HandleEventRequest
                handle_event_request = shared_messages_pb2.HandleEventRequest(
                    simulation_id=sim_id,
                    event=event
                )
                logging.info(f"Sending event {event.event_id} to runtime {runtime_addr} for model {target_model_id}")
                handle_event_response = runtime_stub.HandleEvent(handle_event_request)
                logging.info(f"Received HandleEvent response from runtime for event {event.event_id}: Success={handle_event_response.success}, Generated Events={len(handle_event_response.generated_events)}")

                if handle_event_response.success:
                    processed_events += 1
                    for new_event in handle_event_response.generated_events:
                        if not new_event.source_model_id:
                             new_event.source_model_id = target_model_id
                        success = self._schedule_event(instance, new_event)
                        if success:
                            logging.info(f"Scheduled new event from {target_model_id} for {new_event.target_model_id} at time {new_event.timestamp}")
                        else:
                            logging.error(f"Failed to schedule new event from {target_model_id}")
                else:
                    logging.error(f"Runtime failed to handle event {event.event_id} for model {target_model_id}: {handle_event_response.message}. Bailing out.")
                    runtime_error = True
                    break

            except grpc.RpcError as e:
                logging.error(f"gRPC error calling HandleEvent on runtime {runtime_addr} for event {event.event_id}: {e.code()} - {e.details()}. Bailing out.")
                runtime_error = True
                break
            except Exception as e:
                 logging.error(f"Unexpected error handling event {event.event_id} via runtime: {e}. Bailing out.", exc_info=True)
                 runtime_error = True
                 break

        # Determine final status
        final_time = instance["current_time"]
        final_status = instance["status"]
        if runtime_error:
            instance["status"] = "FAILED"
            final_status = "FAILED"
            success = False
            message = "Runtime error occurred during simulation step."
        elif not instance["event_queue"]:
            completed = True
            instance["status"] = "COMPLETED"
            final_status = "COMPLETED"
            success = True
            message = f"Simulation step executed. Processed {processed_events} events. Simulation completed."
            logging.info(f"Kernel instance {kernel_id} completed simulation.")
        else:
             instance["status"] = "PAUSED"
             final_status = "PAUSED"
             success = True
             message = f"Simulation step executed. Processed {processed_events} events."

        logging.info(f"RunSimulationStep for {kernel_id} finished. Processed {processed_events} events. Current time: {final_time}, Status: {final_status}")
        logging.info(f"Event queue after step: {instance['event_queue']}")

        return kernel_pb2.RunSimulationStepResponse(
            simulation_id=sim_id,
            kernel_instance_id=kernel_id,
            current_simulation_time=final_time,
            completed=completed,
            success=success,
            message=message
        )

    def InjectEvent(self, request, context):
        """Handles request to inject an external event."""
        sim_id = request.simulation_id
        kernel_id = request.kernel_instance_id
        event = request.event
        logging.info(f"Received InjectEvent request for kernel_id: {kernel_id}, event_id: {event.event_id}, time: {event.timestamp}")

        if kernel_id not in simulation_instances:
            logging.warning(f"Kernel instance ID {kernel_id} not found for event injection.")
            return kernel_pb2.InjectEventResponse(success=False, message=f"Kernel instance ID {kernel_id} not found.")

        instance = simulation_instances[kernel_id]
        current_inst_time = instance["current_time"]

        if event.timestamp < current_inst_time:
            logging.warning(f"Cannot inject event {event.event_id} in the past ({event.timestamp} < {current_inst_time}).")
            return kernel_pb2.InjectEventResponse(success=False, message="Cannot inject event in the past.")

        success = self._schedule_event(instance, event, internal_event=False)

        if success:
            logging.info(f"Injected event {event.event_id} scheduled for time {event.timestamp}.")
            return kernel_pb2.InjectEventResponse(success=True, message="Event injected successfully.")
        else:
             return kernel_pb2.InjectEventResponse(success=False, message="Failed to schedule injected event.")

    def TerminateSimulation(self, request, context):
        """Handles request to terminate a simulation instance."""
        sim_id = request.simulation_id
        kernel_id = request.kernel_instance_id
        logging.info(f"Received TerminateSimulation request for kernel_id: {kernel_id}")

        if kernel_id in simulation_instances:
            instance = simulation_instances[kernel_id]
            unload_success = True
            for model_id, model_info in instance.get("models", {}).items():
                runtime_addr = model_info["runtime"]
                if runtime_addr in instance["runtime_stubs"]:
                    runtime_stub = instance["runtime_stubs"][runtime_addr]
                    # Use shared_messages_pb2 for UnloadModelRequest
                    unload_req = shared_messages_pb2.UnloadModelRequest(
                        simulation_id=sim_id, 
                        model_id=model_id
                    )
                    try:
                        logging.info(f"Calling Runtime UnloadModel for model_id: {model_id}")
                        unload_resp = runtime_stub.UnloadModel(unload_req)
                        if not unload_resp.success:
                            logging.warning(f"Runtime failed to unload model {model_id}: {unload_resp.message}")
                            unload_success = False
                    except grpc.RpcError as e:
                         logging.warning(f"gRPC error unloading model {model_id} from runtime {runtime_addr}: {e.code()} - {e.details()}")
                         unload_success = False
                    except Exception as e:
                         logging.warning(f"Unexpected error unloading model {model_id}: {e}")
                         unload_success = False

            # Clean up instance
            del simulation_instances[kernel_id]
            logging.info(f"Kernel instance {kernel_id} terminated.")

            return kernel_pb2.TerminateSimulationResponse(
                success=unload_success,
                message=f"Kernel instance {kernel_id} terminated. Model unload {'succeeded' if unload_success else 'had some failures'}."
            )
        else:
            logging.warning(f"Kernel instance ID {kernel_id} not found for termination.")
            return kernel_pb2.TerminateSimulationResponse(
                success=False,
                message=f"Kernel instance ID {kernel_id} not found."
            )

def serve():
    """Starts the gRPC server."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    kernel_pb2_grpc.add_KernelServiceServicer_to_server(
        KernelServiceServicer(), server
    )
    port = "50052" # Default port for Kernel
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    logging.info(f"Kernel server started on port {port}")
    try:
        while True:
            time.sleep(86400) # Keep server running
    except KeyboardInterrupt:
        logging.info("Stopping server...")
        server.stop(0)

if __name__ == "__main__":
    serve()
