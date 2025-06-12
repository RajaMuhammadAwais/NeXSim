# /home/ubuntu/modern_simulator/kernel/kernel_client.py

import grpc
import logging
import sys

# Add proto directory to path to import generated code
sys.path.append("/home/ubuntu/modern_simulator/proto")

# Import generated gRPC files
import kernel_pb2
import kernel_pb2_grpc

# Basic logging configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def run_client():
    """Runs a simple client to test the KernelService."""
    port = "50052"
    # Use localhost as the server is running in the same environment
    channel = grpc.insecure_channel(f"localhost:{port}")
    stub = kernel_pb2_grpc.KernelServiceStub(channel)

    sim_id = "test_sim_001" # Should match orchestrator if integrating
    kernel_id = "kernel_instance_01"
    scenario = "{\"models\": [\"test_model_1\"]}" # Example config

    try:
        # 1. Initialize Simulation
        logging.info(f"--- Sending InitializeSimulation for kernel {kernel_id} ---")
        init_request = kernel_pb2.InitializeSimulationRequest(
            simulation_id=sim_id,
            kernel_instance_id=kernel_id,
            scenario_config=scenario
        )
        init_response = stub.InitializeSimulation(init_request)
        logging.info(f"InitializeSimulation Response: success={init_response.success}, message=\"{init_response.message}\"")
        assert init_response.success is True

        # 2. Inject an initial event
        logging.info(f"--- Sending InjectEvent for kernel {kernel_id} ---")
        initial_event = kernel_pb2.SimulationEvent(
            event_id="external_event_0", # External events might have predefined IDs
            timestamp=1.0,
            target_model_id="test_model_1"
            # Add Any data if needed
        )
        inject_request = kernel_pb2.InjectEventRequest(
            simulation_id=sim_id,
            kernel_instance_id=kernel_id,
            event=initial_event
        )
        inject_response = stub.InjectEvent(inject_request)
        logging.info(f"InjectEvent Response: success={inject_response.success}, message=\"{inject_response.message}\"")
        assert inject_response.success is True

        # 3. Run Simulation Step (until time 3.5)
        logging.info(f"--- Sending RunSimulationStep for kernel {kernel_id} until 3.5 ---")
        run_request = kernel_pb2.RunSimulationStepRequest(
            simulation_id=sim_id,
            kernel_instance_id=kernel_id,
            run_until_time=3.5
        )
        run_response = stub.RunSimulationStep(run_request)
        logging.info(f"RunSimulationStep Response: success={run_response.success}, time={run_response.current_simulation_time}, completed={run_response.completed}, message=\"{run_response.message}\"")
        assert run_response.success is True
        assert run_response.current_simulation_time == 3.0 # 1.0 (initial) + 1.0 + 1.0
        assert run_response.completed is False

        # 4. Run Simulation Step again (until time 10.0 - should complete)
        logging.info(f"--- Sending RunSimulationStep for kernel {kernel_id} until 10.0 ---")
        run_request_2 = kernel_pb2.RunSimulationStepRequest(
            simulation_id=sim_id,
            kernel_instance_id=kernel_id,
            run_until_time=10.0
        )
        run_response_2 = stub.RunSimulationStep(run_request_2)
        logging.info(f"RunSimulationStep Response 2: success={run_response_2.success}, time={run_response_2.current_simulation_time}, completed={run_response_2.completed}, message=\"{run_response_2.message}\"")
        # Based on placeholder logic, last event is at 3.0 + 1.0 + 1.0 = 5.0
        # The rescheduling limit is run_until + 5.0 = 3.5 + 5.0 = 8.5
        # So events at 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0 should occur
        # Let's refine the placeholder logic and assertion
        # If last event processed was at 3.0, new events scheduled at 4.0, 5.0
        # Run until 10.0: process 4.0 (schedule 6.0), process 5.0 (schedule 7.0), process 6.0 (schedule 8.0), process 7.0 (schedule 9.0), process 8.0 (schedule 10.0), process 9.0 (schedule 11.0), process 10.0 (schedule 12.0)
        # Reschedule limit was 3.5 + 5.0 = 8.5. So only events up to 8.0 are scheduled.
        # Events processed: 1.0, 2.0, 3.0 (in first run). Then 4.0, 5.0, 6.0, 7.0, 8.0 (in second run)
        # Final time should be 8.0
        assert run_response_2.success is True
        assert run_response_2.current_simulation_time == 8.0
        assert run_response_2.completed is False # Queue is not empty yet (event at 9.0 was scheduled but not processed)
        # Let's adjust the placeholder logic slightly in kernel_service.py for simpler testing
        # Let's assume the placeholder reschedule limit is based on the *current* run_until + 5.0
        # Run 1 (until 3.5): Process 1.0 (sched 2.0), 2.0 (sched 3.0), 3.0 (sched 4.0). Current time = 3.0. Limit = 3.5+5=8.5
        # Run 2 (until 10.0): Process 4.0 (sched 5.0), 5.0 (sched 6.0), 6.0 (sched 7.0), 7.0 (sched 8.0), 8.0 (sched 9.0). Limit = 10.0+5=15.0
        # Process 9.0 (sched 10.0). Process 10.0 (sched 11.0). Stop as 11.0 > 10.0. Put 11.0 back.
        # Final time should be 10.0
        # Let's modify kernel placeholder logic to reflect this simpler test case.

        # 5. Terminate Simulation
        logging.info(f"--- Sending TerminateSimulation for kernel {kernel_id} ---")
        term_request = kernel_pb2.TerminateSimulationRequest(simulation_id=sim_id, kernel_instance_id=kernel_id)
        term_response = stub.TerminateSimulation(term_request)
        logging.info(f"TerminateSimulation Response: success={term_response.success}, message=\"{term_response.message}\"")
        assert term_response.success is True

        # 6. Try to run step again (should fail)
        logging.info(f"--- Sending RunSimulationStep for kernel {kernel_id} after termination (should fail) ---")
        run_request_fail = kernel_pb2.RunSimulationStepRequest(
            simulation_id=sim_id,
            kernel_instance_id=kernel_id,
            run_until_time=15.0
        )
        run_response_fail = stub.RunSimulationStep(run_request_fail)
        logging.info(f"RunSimulationStep Response (fail): success={run_response_fail.success}, message=\"{run_response_fail.message}\"")
        assert run_response_fail.success is False

        logging.info("--- Kernel client tests completed successfully (basic checks) ---")

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

