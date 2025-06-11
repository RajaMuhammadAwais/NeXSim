#!/usr/bin/env python3.11
# Simple test script to verify kernel service responsiveness

import sys
import logging
import grpc
import time

# Add proto directory to path
sys.path.append("/home/ubuntu/modern_simulator/proto")

# Import generated gRPC files
import kernel_pb2
import kernel_pb2_grpc
import shared_messages_pb2

# Configure logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

def test_kernel_service():
    """Test basic connectivity and responsiveness of the kernel service."""
    try:
        # Connect to kernel service
        logging.info("Attempting to connect to Kernel service at localhost:50052")
        channel = grpc.insecure_channel("localhost:50052")
        
        # Wait for channel to be ready
        try:
            grpc.channel_ready_future(channel).result(timeout=5)
            logging.info("Successfully connected to Kernel service")
        except grpc.FutureTimeoutError:
            logging.error("Timeout waiting for Kernel service to be ready")
            return False
        
        # Create stub
        stub = kernel_pb2_grpc.KernelServiceStub(channel)
        logging.info("Created Kernel service stub")
        
        # Create a test simulation ID
        sim_id = "test-kernel-responsiveness"
        kernel_id = f"kernel-{sim_id}"
        
        # Create a simple initialization request
        logging.info(f"Creating InitializeSimulation request for sim_id: {sim_id}, kernel_id: {kernel_id}")
        init_request = kernel_pb2.InitializeSimulationRequest(
            simulation_id=sim_id,
            kernel_instance_id=kernel_id,
            scenario_config='{"nodes": [{"model_id": "test_node", "model_type": "python:BasicNodeModel", "config": {}}], "initial_events": [{"timestamp": 0.0, "target_model_id": "test_node", "event_type": "START"}]}'
        )
        
        # Send the request
        logging.info("Sending InitializeSimulation request to Kernel service")
        try:
            init_response = stub.InitializeSimulation(init_request)
            logging.info(f"Received InitializeSimulation response: success={init_response.success}, message={init_response.message}")
            
            if init_response.success:
                logging.info("Kernel service responded successfully to initialization request")
                
                # Try running a simulation step
                logging.info(f"Creating RunSimulationStep request for kernel_id: {kernel_id}")
                run_request = kernel_pb2.RunSimulationStepRequest(
                    simulation_id=sim_id,
                    kernel_instance_id=kernel_id,
                    run_until_time=10.0
                )
                
                logging.info("Sending RunSimulationStep request to Kernel service")
                run_response = stub.RunSimulationStep(run_request)
                logging.info(f"Received RunSimulationStep response: success={run_response.success}, message={run_response.message}, time={run_response.current_simulation_time}")
                
                # Clean up
                logging.info(f"Creating TerminateSimulation request for kernel_id: {kernel_id}")
                term_request = kernel_pb2.TerminateSimulationRequest(
                    simulation_id=sim_id,
                    kernel_instance_id=kernel_id
                )
                
                logging.info("Sending TerminateSimulation request to Kernel service")
                term_response = stub.TerminateSimulation(term_request)
                logging.info(f"Received TerminateSimulation response: success={term_response.success}, message={term_response.message}")
                
                return True
            else:
                logging.error(f"Kernel service initialization failed: {init_response.message}")
                return False
                
        except grpc.RpcError as e:
            logging.error(f"gRPC error calling Kernel service: {e.code()} - {e.details()}")
            return False
        except Exception as e:
            logging.error(f"Unexpected error testing Kernel service: {e}", exc_info=True)
            return False
            
    except Exception as e:
        logging.error(f"Error in test_kernel_service: {e}", exc_info=True)
        return False
    finally:
        if 'channel' in locals():
            channel.close()

if __name__ == "__main__":
    logging.info("Starting Kernel service test")
    success = test_kernel_service()
    if success:
        logging.info("Kernel service test completed successfully")
        sys.exit(0)
    else:
        logging.error("Kernel service test failed")
        sys.exit(1)
