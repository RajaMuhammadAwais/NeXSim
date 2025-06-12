# /home/ubuntu/modern_simulator/orchestrator/orchestrator_service.py

import grpc
import time
from concurrent import futures
import logging
import sys
import uuid
import os
import subprocess
import psutil

# Add proto directory to path to import generated code
sys.path.append("/home/ubuntu/modern_simulator/proto")

# Import generated gRPC files
import orchestrator_pb2
import orchestrator_pb2_grpc
import kernel_pb2
import kernel_pb2_grpc
import shared_messages_pb2

# Set DEBUG level logging configuration
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

# In-memory storage for simulation status (for MVP)
# Key: simulation_id, Value: dict containing state
simulations = {}

# Kernel service connection details (assuming it runs locally for MVP)
KERNEL_SERVICE_ADDRESS = "localhost:50052"

class OrchestratorServiceServicer(orchestrator_pb2_grpc.OrchestratorServiceServicer):
    """Provides methods that implement functionality of the orchestrator server."""

    def __init__(self):
        """Initialize the orchestrator service."""
        self.own_pid = os.getpid()
        logging.info(f"Orchestrator service initialized with PID: {self.own_pid}")
        self._check_kernel_process()

    def _check_kernel_process(self):
        """Check if kernel process is running and log its details."""
        try:
            # Find all Python processes
            python_processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if 'python' in proc.info['name'].lower():
                        python_processes.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            
            # Find kernel service process
            kernel_processes = []
            for proc in python_processes:
                try:
                    cmdline = proc.info['cmdline']
                    if cmdline and any('kernel_service.py' in arg for arg in cmdline):
                        kernel_processes.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            
            if kernel_processes:
                for kernel_proc in kernel_processes:
                    pid = kernel_proc.info['pid']
                    cmdline = ' '.join(kernel_proc.info['cmdline'])
                    create_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(kernel_proc.create_time()))
                    logging.info(f"Found kernel process: PID={pid}, Created={create_time}, Command={cmdline}")
            else:
                logging.warning("No kernel service process found running!")
        except Exception as e:
            logging.error(f"Error checking kernel process: {e}", exc_info=True)

    def _get_kernel_stub(self):
        """Creates a gRPC stub for the Kernel service."""
        # In a real system, channel management might be more sophisticated
        logging.info(f"Creating gRPC channel to Kernel service at {KERNEL_SERVICE_ADDRESS}")
        
        # Check kernel process before connecting
        self._check_kernel_process()
        
        channel = grpc.insecure_channel(KERNEL_SERVICE_ADDRESS)
        # Add channel readiness check
        try:
            grpc.channel_ready_future(channel).result(timeout=5)
            logging.info(f"Channel to Kernel service is ready")
        except grpc.FutureTimeoutError:
            logging.error(f"Timeout waiting for channel to Kernel service to be ready")
            raise
        return kernel_pb2_grpc.KernelServiceStub(channel)

    def StartSimulation(self, request, context):
        """Handles request to start a new simulation."""
        sim_id = request.simulation_id
        logging.info(f"Received StartSimulation request for ID: {sim_id}")
        logging.debug(f"StartSimulation request details: simulation_id={sim_id}, scenario_config length={len(request.scenario_config)}")

        if sim_id in simulations:
            logging.warning(f"Simulation ID {sim_id} already exists.")
            return orchestrator_pb2.StartSimulationResponse(
                simulation_id=sim_id,
                success=False,
                message=f"Simulation ID {sim_id} already exists."
            )

        # Mark as PENDING initially
        simulations[sim_id] = {
            "status": orchestrator_pb2.GetSimulationStatusResponse.Status.PENDING,
            "config": request.scenario_config,
            "current_time": 0.0,
            "kernel_instance_id": None
        }
        logging.info(f"Simulation {sim_id} marked as PENDING.")

        # Generate a unique kernel instance ID
        kernel_instance_id = f"kernel-{sim_id}-{uuid.uuid4()}"
        simulations[sim_id]["kernel_instance_id"] = kernel_instance_id
        logging.debug(f"Generated kernel_instance_id: {kernel_instance_id}")

        try:
            # Connect to Kernel Service
            logging.info(f"Attempting to connect to Kernel service for simulation {sim_id}")
            kernel_stub = self._get_kernel_stub()
            
            # Prepare initialization request
            init_request = kernel_pb2.InitializeSimulationRequest(
                simulation_id=sim_id,
                kernel_instance_id=kernel_instance_id,
                scenario_config=request.scenario_config
            )
            logging.info(f"Calling Kernel InitializeSimulation for kernel_id: {kernel_instance_id}")
            logging.debug(f"InitializeSimulation request details: simulation_id={sim_id}, kernel_instance_id={kernel_instance_id}")
            
            # Log the full request for debugging
            logging.info(f"InitializeSimulation request content: {init_request}")
            
            # Make the gRPC call to kernel
            logging.info(f"Sending InitializeSimulation request to Kernel service at {KERNEL_SERVICE_ADDRESS}")
            start_time = time.time()
            init_response = kernel_stub.InitializeSimulation(init_request)
            end_time = time.time()
            logging.info(f"Received InitializeSimulation response after {end_time - start_time:.3f}s: success={init_response.success}, message={init_response.message}")

            # Check kernel process after request
            self._check_kernel_process()

            if init_response.success:
                simulations[sim_id]["status"] = orchestrator_pb2.GetSimulationStatusResponse.Status.RUNNING
                logging.info(f"Kernel instance {kernel_instance_id} initialized successfully. Simulation {sim_id} is now RUNNING.")
                
                # Try to run a simulation step immediately to advance time
                try:
                    logging.info(f"Attempting to run initial simulation step for {sim_id}")
                    run_request = kernel_pb2.RunSimulationStepRequest(
                        simulation_id=sim_id,
                        kernel_instance_id=kernel_instance_id,
                        run_until_time=10.0  # Run for a while
                    )
                    logging.info(f"Sending RunSimulationStep request to Kernel service")
                    run_response = kernel_stub.RunSimulationStep(run_request)
                    logging.info(f"Received RunSimulationStep response: success={run_response.success}, message={run_response.message}, time={run_response.current_simulation_time}")
                    
                    if run_response.success:
                        simulations[sim_id]["current_time"] = run_response.current_simulation_time
                        logging.info(f"Updated simulation time to {run_response.current_simulation_time}")
                    else:
                        logging.warning(f"Failed to run simulation step: {run_response.message}")
                except Exception as e:
                    logging.error(f"Error running initial simulation step: {e}", exc_info=True)
                
                return orchestrator_pb2.StartSimulationResponse(
                    simulation_id=sim_id,
                    success=True,
                    message=f"Simulation {sim_id} initiated successfully."
                )
            else:
                simulations[sim_id]["status"] = orchestrator_pb2.GetSimulationStatusResponse.Status.FAILED
                error_msg = f"Failed to initialize kernel instance {kernel_instance_id}: {init_response.message}"
                logging.error(error_msg)
                return orchestrator_pb2.StartSimulationResponse(
                    simulation_id=sim_id,
                    success=False,
                    message=error_msg
                )

        except grpc.RpcError as e:
            simulations[sim_id]["status"] = orchestrator_pb2.GetSimulationStatusResponse.Status.FAILED
            error_msg = f"gRPC error connecting to kernel or initializing simulation {sim_id}: {e.code()} - {e.details()}"
            logging.error(error_msg)
            return orchestrator_pb2.StartSimulationResponse(
                simulation_id=sim_id,
                success=False,
                message=error_msg
            )
        except Exception as e:
            simulations[sim_id]["status"] = orchestrator_pb2.GetSimulationStatusResponse.Status.FAILED
            error_msg = f"Unexpected error starting simulation {sim_id}: {e}"
            logging.error(error_msg, exc_info=True)
            return orchestrator_pb2.StartSimulationResponse(
                simulation_id=sim_id,
                success=False,
                message=error_msg
            )

    def StopSimulation(self, request, context):
        """Handles request to stop a simulation."""
        sim_id = request.simulation_id
        logging.info(f"Received StopSimulation request for ID: {sim_id}")
        logging.debug(f"StopSimulation request details: simulation_id={sim_id}")

        if sim_id not in simulations:
            logging.warning(f"Simulation ID {sim_id} not found for stopping.")
            return orchestrator_pb2.StopSimulationResponse(
                simulation_id=sim_id,
                success=False,
                message=f"Simulation ID {sim_id} not found."
            )

        sim_info = simulations[sim_id]
        kernel_instance_id = sim_info.get("kernel_instance_id")
        current_status = sim_info["status"]
        logging.debug(f"Current simulation status: {current_status}, kernel_instance_id: {kernel_instance_id}")

        if current_status not in [
            orchestrator_pb2.GetSimulationStatusResponse.Status.RUNNING,
            orchestrator_pb2.GetSimulationStatusResponse.Status.PENDING,
            orchestrator_pb2.GetSimulationStatusResponse.Status.FAILED
        ]:
            logging.warning(f"Simulation {sim_id} is not in a stoppable state (current: {current_status}).")
            return orchestrator_pb2.StopSimulationResponse(
                simulation_id=sim_id,
                success=False,
                message=f"Simulation {sim_id} is not running, pending, or failed."
            )

        if not kernel_instance_id:
             logging.warning(f"No kernel_instance_id found for simulation {sim_id}. Marking as STOPPED.")
             sim_info["status"] = orchestrator_pb2.GetSimulationStatusResponse.Status.STOPPED
             return orchestrator_pb2.StopSimulationResponse(
                 simulation_id=sim_id,
                 success=True,
                 message=f"Simulation {sim_id} marked as stopped (no kernel instance found)."
             )

        try:
            # Connect to Kernel Service
            logging.info(f"Attempting to connect to Kernel service to stop simulation {sim_id}")
            kernel_stub = self._get_kernel_stub()
            
            # Prepare termination request
            term_request = kernel_pb2.TerminateSimulationRequest(
                simulation_id=sim_id,
                kernel_instance_id=kernel_instance_id
            )
            logging.info(f"Calling Kernel TerminateSimulation for kernel_id: {kernel_instance_id}")
            logging.debug(f"TerminateSimulation request details: simulation_id={sim_id}, kernel_instance_id={kernel_instance_id}")
            
            # Make the gRPC call to kernel
            logging.info(f"Sending TerminateSimulation request to Kernel service")
            term_response = kernel_stub.TerminateSimulation(term_request)
            logging.info(f"Received TerminateSimulation response: success={term_response.success}, message={term_response.message}")

            if term_response.success:
                sim_info["status"] = orchestrator_pb2.GetSimulationStatusResponse.Status.STOPPED
                logging.info(f"Kernel instance {kernel_instance_id} terminated successfully. Simulation {sim_id} marked as STOPPED.")
                return orchestrator_pb2.StopSimulationResponse(
                    simulation_id=sim_id,
                    success=True,
                    message=f"Simulation {sim_id} and kernel instance stopped successfully."
                )
            else:
                sim_info["status"] = orchestrator_pb2.GetSimulationStatusResponse.Status.STOPPED
                error_msg = f"Kernel failed to terminate instance {kernel_instance_id}: {term_response.message}. Simulation {sim_id} marked as STOPPED."
                logging.error(error_msg)
                return orchestrator_pb2.StopSimulationResponse(
                    simulation_id=sim_id,
                    success=False,
                    message=error_msg
                )

        except grpc.RpcError as e:
            sim_info["status"] = orchestrator_pb2.GetSimulationStatusResponse.Status.STOPPED
            error_msg = f"gRPC error connecting to kernel or terminating simulation {sim_id}: {e.code()} - {e.details()}. Marked as STOPPED."
            logging.error(error_msg)
            return orchestrator_pb2.StopSimulationResponse(
                simulation_id=sim_id,
                success=False,
                message=error_msg
            )
        except Exception as e:
            sim_info["status"] = orchestrator_pb2.GetSimulationStatusResponse.Status.STOPPED
            error_msg = f"Unexpected error stopping simulation {sim_id}: {e}. Marked as STOPPED."
            logging.error(error_msg, exc_info=True)
            return orchestrator_pb2.StopSimulationResponse(
                simulation_id=sim_id,
                success=False,
                message=error_msg
            )

    def GetSimulationStatus(self, request, context):
        """Handles request to get the status of a simulation."""
        sim_id = request.simulation_id
        logging.info(f"Received GetSimulationStatus request for ID: {sim_id}")
        logging.debug(f"GetSimulationStatus request details: simulation_id={sim_id}")

        if sim_id not in simulations:
            logging.warning(f"Simulation ID {sim_id} not found for status check.")
            return orchestrator_pb2.GetSimulationStatusResponse(
                simulation_id=sim_id,
                status=orchestrator_pb2.GetSimulationStatusResponse.Status.UNKNOWN,
                message=f"Simulation ID {sim_id} not found."
            )

        # Get current status from orchestrator's view
        status_info = simulations[sim_id]
        current_status = status_info["status"]
        current_time = status_info.get("current_time", 0.0)
        kernel_instance_id = status_info.get("kernel_instance_id")
        
        logging.debug(f"Current status for {sim_id}: status={current_status}, time={current_time}, kernel_id={kernel_instance_id}")
        
        # If simulation is running, try to get updated time from kernel
        if current_status == orchestrator_pb2.GetSimulationStatusResponse.Status.RUNNING and kernel_instance_id:
            try:
                logging.info(f"Attempting to get updated simulation time from kernel for {sim_id}")
                kernel_stub = self._get_kernel_stub()
                
                # Try to run a simulation step to advance time
                try:
                    run_request = kernel_pb2.RunSimulationStepRequest(
                        simulation_id=sim_id,
                        kernel_instance_id=kernel_instance_id,
                        run_until_time=current_time + 5.0  # Run for a bit more
                    )
                    logging.info(f"Sending RunSimulationStep request to Kernel service")
                    run_response = kernel_stub.RunSimulationStep(run_request)
                    logging.info(f"Received RunSimulationStep response: success={run_response.success}, message={run_response.message}, time={run_response.current_simulation_time}")
                    
                    if run_response.success:
                        current_time = run_response.current_simulation_time
                        status_info["current_time"] = current_time
                        logging.info(f"Updated simulation time to {current_time}")
                    else:
                        logging.warning(f"Failed to run simulation step: {run_response.message}")
                except Exception as e:
                    logging.error(f"Error running simulation step during status check: {e}", exc_info=True)
                
            except Exception as e:
                logging.error(f"Error getting updated time from kernel for {sim_id}: {e}")
                # Continue with stored time
        
        logging.info(f"Returning status for {sim_id}: {current_status}, time={current_time}")
        return orchestrator_pb2.GetSimulationStatusResponse(
            simulation_id=sim_id,
            status=current_status,
            current_simulation_time=current_time,
            message=f"Status for {sim_id} retrieved from orchestrator."
        )

def serve():
    """Starts the gRPC server."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    orchestrator_pb2_grpc.add_OrchestratorServiceServicer_to_server(
        OrchestratorServiceServicer(), server
    )
    port = "50051" # Default port for Orchestrator
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    logging.info(f"Orchestrator server started on port {port}")
    try:
        while True:
            time.sleep(86400) # Keep server running
    except KeyboardInterrupt:
        logging.info("Stopping server...")
        server.stop(0)

if __name__ == "__main__":
    serve()
