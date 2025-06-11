#!/usr/bin/env python3.11
# /home/ubuntu/modern_simulator/run_simulation.py

import grpc
import logging
import sys
import time
import subprocess
import os
import json
import uuid # Import uuid module

# Add proto directory to path
sys.path.append("/home/ubuntu/modern_simulator/proto")

# Import generated gRPC files
import orchestrator_pb2
import orchestrator_pb2_grpc
import kernel_pb2 # For status checking if needed directly

# Basic logging configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

ORCHESTRATOR_PORT = "50051"
KERNEL_PORT = "50052"
RUNTIME_PORT = "50053"

ORCHESTRATOR_SERVICE_FILE = "/home/ubuntu/modern_simulator/orchestrator/orchestrator_service.py"
KERNEL_SERVICE_FILE = "/home/ubuntu/modern_simulator/kernel/kernel_service.py"
RUNTIME_SERVICE_FILE = "/home/ubuntu/modern_simulator/runtime/runtime_service.py"
SCENARIO_FILE = "/home/ubuntu/modern_simulator/scenarios/scenario_basic.json"

def start_service(service_file, port):
    """Starts a gRPC service in the background."""
    # Create log file name based on service file
    log_file_name = os.path.basename(service_file).replace(".py", ".log")
    log_file_path = f"/home/ubuntu/modern_simulator/logs/{log_file_name}"
    
    # Ensure logs directory exists
    os.makedirs("/home/ubuntu/modern_simulator/logs", exist_ok=True)
    
    # Open log file for writing
    log_file = open(log_file_path, "w")
    
    cmd = ["python3.11", service_file]
    cmd_str = " ".join(cmd)
    logging.info(f"Starting service: {cmd_str}")
    logging.info(f"Redirecting output to: {log_file_path}")
    
    # Redirect stdout and stderr to the log file
    process = subprocess.Popen(cmd, stdout=log_file, stderr=log_file, text=True)
    time.sleep(2) # Give the server a moment to start
    if process.poll() is not None:
         # Close log file if process failed to start
         log_file.close()
         logging.error(f"Failed to start {service_file}. Exit code: {process.returncode}")
         logging.error(f"Check {log_file_path} for details")
         return None
    logging.info(f"Service {service_file} started with PID {process.pid} on port {port}.")
    
    # Store log file handle in process object for later closing
    process.log_file = log_file
    return process

def run_simulation_scenario(scenario_path):
    """Runs the simulation defined in the scenario file."""
    orchestrator_process = None
    kernel_process = None
    runtime_process = None

    try:
        # 1. Start Services
        logging.info("--- Starting Services ---")
        runtime_process = start_service(RUNTIME_SERVICE_FILE, RUNTIME_PORT)
        if not runtime_process: raise Exception("Failed to start Runtime Service")

        kernel_process = start_service(KERNEL_SERVICE_FILE, KERNEL_PORT)
        if not kernel_process: raise Exception("Failed to start Kernel Service")

        orchestrator_process = start_service(ORCHESTRATOR_SERVICE_FILE, ORCHESTRATOR_PORT)
        if not orchestrator_process: raise Exception("Failed to start Orchestrator Service")

        logging.info("All services started. Waiting a bit more...")
        time.sleep(3)

        # 2. Connect to Orchestrator
        logging.info("--- Connecting to Orchestrator ---")
        channel = grpc.insecure_channel(f"localhost:{ORCHESTRATOR_PORT}")
        try:
            grpc.channel_ready_future(channel).result(timeout=10)
        except grpc.FutureTimeoutError:
            logging.error("Failed to connect to Orchestrator service.")
            raise

        stub = orchestrator_pb2_grpc.OrchestratorServiceStub(channel)
        logging.info("Connected to Orchestrator.")

        # 3. Load Scenario and Generate Unique Sim ID
        logging.info(f"--- Loading Scenario: {scenario_path} ---")
        with open(scenario_path, "r") as f:
            scenario_data = json.load(f)
            scenario_config_str = json.dumps(scenario_data)
            base_sim_id = scenario_data.get("simulation_id", "default_sim")
            # Generate a unique simulation ID for this run
            unique_suffix = uuid.uuid4().hex[:8]
            sim_id = f"{base_sim_id}-{unique_suffix}"
            logging.info(f"Using unique simulation ID: {sim_id}")
            sim_duration = scenario_data.get("duration", 10.0)

        # 4. Start Simulation with Unique ID
        logging.info(f"--- Starting Simulation: {sim_id} ---")
        start_request = orchestrator_pb2.StartSimulationRequest(
            simulation_id=sim_id, # Use the unique ID
            scenario_config=scenario_config_str
        )
        start_response = stub.StartSimulation(start_request)
        logging.info(f"StartSimulation Response: success={start_response.success}, message=\"{start_response.message}\"")
        if not start_response.success:
            raise Exception(f"Failed to start simulation: {start_response.message}")

        # 5. Monitor Simulation (Basic Polling)
        logging.info(f"--- Monitoring Simulation (Polling Status) ---")
        status_request = orchestrator_pb2.GetSimulationStatusRequest(simulation_id=sim_id) # Use the unique ID
        final_status = orchestrator_pb2.GetSimulationStatusResponse.Status.UNKNOWN
        start_time = time.time()
        max_monitor_time = 60 # Max time to monitor in seconds
        while True:
            if time.time() - start_time > max_monitor_time:
                logging.warning(f"Monitoring timeout ({max_monitor_time}s) reached for simulation {sim_id}. Stopping.")
                final_status = orchestrator_pb2.GetSimulationStatusResponse.Status.STOPPED # Assume stopped due to timeout
                break
            try:
                status_response = stub.GetSimulationStatus(status_request)
                current_status = status_response.status
                current_time = status_response.current_simulation_time
                status_name = orchestrator_pb2.GetSimulationStatusResponse.Status.Name(current_status)
                logging.info(f"Simulation Status: {status_name}, Sim Time: {current_time:.2f}")

                if current_status in [
                    orchestrator_pb2.GetSimulationStatusResponse.Status.COMPLETED,
                    orchestrator_pb2.GetSimulationStatusResponse.Status.FAILED,
                    orchestrator_pb2.GetSimulationStatusResponse.Status.STOPPED
                ]:
                    final_status = current_status
                    logging.info(f"Simulation {sim_id} finished with status: {status_name}")
                    break

            except grpc.RpcError as e:
                logging.error(f"gRPC error getting status: {e.code()} - {e.details()}")
                final_status = orchestrator_pb2.GetSimulationStatusResponse.Status.FAILED
                break

            time.sleep(2)

        # 6. Stop Simulation (ensure cleanup via orchestrator)
        logging.info(f"--- Stopping Simulation: {sim_id} (Final Status: {orchestrator_pb2.GetSimulationStatusResponse.Status.Name(final_status)}) ---")
        stop_request = orchestrator_pb2.StopSimulationRequest(simulation_id=sim_id) # Use the unique ID
        try:
            stop_response = stub.StopSimulation(stop_request)
            logging.info(f"StopSimulation Response: success={stop_response.success}, message=\"{stop_response.message}\"")
        except grpc.RpcError as e:
            logging.error(f"gRPC error stopping simulation: {e.code()} - {e.details()}")

        channel.close()

    except Exception as e:
        logging.error(f"An error occurred during simulation run: {e}", exc_info=True)
    finally:
        # 7. Terminate Services
        logging.info("--- Terminating Services ---")
        for process, name in [
            (orchestrator_process, "Orchestrator"),
            (kernel_process, "Kernel"),
            (runtime_process, "Runtime")
        ]:
            if process and process.poll() is None:
                logging.info(f"Terminating {name} service (PID: {process.pid})...")
                process.terminate()
                try:
                    process.wait(timeout=5)
                    logging.info(f"{name} service terminated.")
                except subprocess.TimeoutExpired:
                    logging.warning(f"{name} service did not terminate gracefully, killing...")
                    process.kill()
                    process.wait()
                    logging.info(f"{name} service killed.")
                # Close the log file
                if hasattr(process, 'log_file'):
                    process.log_file.close()
            elif process:
                 logging.info(f"{name} service (PID: {process.pid}) already stopped.")
                 # Close the log file
                 if hasattr(process, 'log_file'):
                     process.log_file.close()
            else:
                 logging.info(f"{name} service was not started or failed to start.")

if __name__ == "__main__":
    run_simulation_scenario(SCENARIO_FILE)

