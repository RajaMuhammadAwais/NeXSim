# /home/ubuntu/modern_simulator/orchestrator/orchestrator_client.py

import grpc
import logging
import sys

# Add proto directory to path to import generated code
sys.path.append("/home/ubuntu/modern_simulator/proto")

# Import generated gRPC files
import orchestrator_pb2
import orchestrator_pb2_grpc

# Basic logging configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def run_client():
    """Runs a simple client to test the OrchestratorService."""
    port = "50051"
    # Use localhost as the server is running in the same environment
    channel = grpc.insecure_channel(f"localhost:{port}")
    stub = orchestrator_pb2_grpc.OrchestratorServiceStub(channel)

    sim_id = "test_sim_001"
    scenario = "{\"nodes\": 2, \"links\": 1}" # Example config

    try:
        # 1. Start Simulation
        logging.info(f"--- Sending StartSimulation for {sim_id} ---")
        start_request = orchestrator_pb2.StartSimulationRequest(simulation_id=sim_id, scenario_config=scenario)
        start_response = stub.StartSimulation(start_request)
        logging.info(f"StartSimulation Response: success={start_response.success}, message=\"{start_response.message}\"")
        assert start_response.success is True

        # 2. Get Status (should be RUNNING)
        logging.info(f"--- Sending GetSimulationStatus for {sim_id} (after start) ---")
        status_request = orchestrator_pb2.GetSimulationStatusRequest(simulation_id=sim_id)
        status_response = stub.GetSimulationStatus(status_request)
        logging.info(f"GetSimulationStatus Response: status={orchestrator_pb2.GetSimulationStatusResponse.Status.Name(status_response.status)}, time={status_response.current_simulation_time}, message=\"{status_response.message}\"")
        assert status_response.status == orchestrator_pb2.GetSimulationStatusResponse.Status.RUNNING

        # 3. Try starting the same simulation again (should fail)
        logging.info(f"--- Sending StartSimulation for {sim_id} again (should fail) ---")
        start_request_again = orchestrator_pb2.StartSimulationRequest(simulation_id=sim_id, scenario_config=scenario)
        start_response_again = stub.StartSimulation(start_request_again)
        logging.info(f"StartSimulation Response (again): success={start_response_again.success}, message=\"{start_response_again.message}\"")
        assert start_response_again.success is False

        # 4. Stop Simulation
        logging.info(f"--- Sending StopSimulation for {sim_id} ---")
        stop_request = orchestrator_pb2.StopSimulationRequest(simulation_id=sim_id)
        stop_response = stub.StopSimulation(stop_request)
        logging.info(f"StopSimulation Response: success={stop_response.success}, message=\"{stop_response.message}\"")
        assert stop_response.success is True

        # 5. Get Status (should be STOPPED)
        logging.info(f"--- Sending GetSimulationStatus for {sim_id} (after stop) ---")
        status_request_after_stop = orchestrator_pb2.GetSimulationStatusRequest(simulation_id=sim_id)
        status_response_after_stop = stub.GetSimulationStatus(status_request_after_stop)
        logging.info(f"GetSimulationStatus Response (after stop): status={orchestrator_pb2.GetSimulationStatusResponse.Status.Name(status_response_after_stop.status)}, time={status_response_after_stop.current_simulation_time}, message=\"{status_response_after_stop.message}\"")
        assert status_response_after_stop.status == orchestrator_pb2.GetSimulationStatusResponse.Status.STOPPED

        # 6. Try stopping again (should fail)
        logging.info(f"--- Sending StopSimulation for {sim_id} again (should fail) ---")
        stop_request_again = orchestrator_pb2.StopSimulationRequest(simulation_id=sim_id)
        stop_response_again = stub.StopSimulation(stop_request_again)
        logging.info(f"StopSimulation Response (again): success={stop_response_again.success}, message=\"{stop_response_again.message}\"")
        assert stop_response_again.success is False

        # 7. Get status for non-existent sim
        logging.info(f"--- Sending GetSimulationStatus for non_existent_sim ---")
        status_request_nonexist = orchestrator_pb2.GetSimulationStatusRequest(simulation_id="non_existent_sim")
        status_response_nonexist = stub.GetSimulationStatus(status_request_nonexist)
        logging.info(f"GetSimulationStatus Response (non-existent): status={orchestrator_pb2.GetSimulationStatusResponse.Status.Name(status_response_nonexist.status)}, message=\"{status_response_nonexist.message}\"")
        assert status_response_nonexist.status == orchestrator_pb2.GetSimulationStatusResponse.Status.UNKNOWN

        logging.info("--- Client tests completed successfully ---")

    except grpc.RpcError as e:
        logging.error(f"gRPC call failed: {e.code()} - {e.details()}")
    except AssertionError as e:
        logging.error(f"Assertion failed: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
    finally:
        channel.close()

if __name__ == "__main__":
    run_client()

