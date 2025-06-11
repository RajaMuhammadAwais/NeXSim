# /home/ubuntu/modern_simulator/runtime/runtime_service.py

import grpc
import time
from concurrent import futures
import logging
import sys
import importlib
import json

# Add proto and models directory to path
sys.path.append("/home/ubuntu/modern_simulator/proto")
sys.path.append("/home/ubuntu/modern_simulator/models")

# Import generated gRPC files
import runtime_pb2
import runtime_pb2_grpc
import shared_messages_pb2  # Import shared message definitions

# Basic logging configuration - SET TO DEBUG
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

# In-memory storage for loaded model instances (for MVP)
# Key: model_id, Value: model instance object
loaded_models = {}

class RuntimeServiceServicer(runtime_pb2_grpc.RuntimeServiceServicer):
    """Provides methods that implement functionality of the runtime server."""

    def LoadModel(self, request, context):
        """Handles request from Kernel to load a model instance."""
        sim_id = request.simulation_id
        model_id = request.model_id
        model_type = request.model_type # e.g., "python:BasicNodeModel"
        model_config = request.model_config
        logging.info(f"Received LoadModel request for model_id: {model_id}, type: {model_type}")

        if model_id in loaded_models:
            logging.warning(f"Model ID {model_id} already loaded.")
            return shared_messages_pb2.LoadModelResponse(
                model_id=model_id,
                success=True,
                message=f"Model ID {model_id} was already loaded."
            )

        try:
            lang, model_class_name = model_type.split(":", 1)
            if lang.lower() != "python":
                raise ValueError(f"Unsupported model language: {lang}")

            module_name = model_class_name.lower()
            if model_class_name == "BasicNodeModel":
                 module_name = "basic_node"
            else:
                 raise ValueError(f"Unknown model class name mapping: {model_class_name}")

            model_module = importlib.import_module(module_name)
            ModelClass = getattr(model_module, model_class_name)

            model_instance = ModelClass(model_id, model_config)
            loaded_models[model_id] = model_instance

            logging.info(f"Successfully loaded model {model_id} of type {model_type}.")
            return shared_messages_pb2.LoadModelResponse(
                model_id=model_id,
                success=True,
                message=f"Model {model_id} loaded successfully."
            )

        except ModuleNotFoundError:
            error_msg = f"Failed to load model {model_id}: Module \'{module_name}\' not found."
            logging.error(error_msg)
            return shared_messages_pb2.LoadModelResponse(model_id=model_id, success=False, message=error_msg)
        except AttributeError:
            error_msg = f"Failed to load model {model_id}: Class \'{model_class_name}\' not found in module \'{module_name}\'."
            logging.error(error_msg)
            return shared_messages_pb2.LoadModelResponse(model_id=model_id, success=False, message=error_msg)
        except Exception as e:
            error_msg = f"Failed to load model {model_id}: {e}"
            logging.error(error_msg, exc_info=True)
            return shared_messages_pb2.LoadModelResponse(model_id=model_id, success=False, message=error_msg)

    def HandleEvent(self, request, context):
        """Handles request from Kernel to process an event."""
        sim_id = request.simulation_id
        event = request.event
        model_id = event.target_model_id
        logging.debug(f"Received HandleEvent request for model_id: {model_id}, event_id: {event.event_id}, time: {event.timestamp}")

        if model_id not in loaded_models:
            error_msg = f"Model {model_id} not found in this runtime instance."
            logging.warning(error_msg)
            return shared_messages_pb2.HandleEventResponse(
                event_id=event.event_id,
                success=False,
                message=error_msg
            )

        try:
            model_instance = loaded_models[model_id]
            current_time = event.timestamp

            # Call the model's event handler
            logging.debug(f"Calling handle_event on model {model_id} instance...")
            generated_events = model_instance.handle_event(current_time, event)
            logging.debug(f"Model {model_id} handle_event returned {len(generated_events)} events.")
            for i, gen_event in enumerate(generated_events):
                logging.debug(f"  Generated Event {i}: Time={gen_event.timestamp}, Target={gen_event.target_model_id}, Source={gen_event.source_model_id}, TypeURL={gen_event.event_data.type_url}")

            return shared_messages_pb2.HandleEventResponse(
                event_id=event.event_id,
                success=True,
                message=f"Event {event.event_id} processed successfully.",
                generated_events=generated_events
            )

        except Exception as e:
            error_msg = f"Error handling event {event.event_id} in model {model_id}: {e}"
            logging.error(error_msg, exc_info=True)
            return shared_messages_pb2.HandleEventResponse(
                event_id=event.event_id,
                success=False,
                message=error_msg
            )

    def UnloadModel(self, request, context):
        """Handles request from Kernel to unload a model instance."""
        sim_id = request.simulation_id
        model_id = request.model_id
        logging.info(f"Received UnloadModel request for model_id: {model_id}")

        if model_id in loaded_models:
            del loaded_models[model_id]
            logging.info(f"Model {model_id} unloaded successfully.")
            return shared_messages_pb2.UnloadModelResponse(
                model_id=model_id,
                success=True,
                message=f"Model {model_id} unloaded successfully."
            )
        else:
            logging.warning(f"Model {model_id} not found for unloading.")
            return shared_messages_pb2.UnloadModelResponse(
                model_id=model_id,
                success=False,
                message=f"Model {model_id} not found."
            )

def serve():
    """Starts the gRPC server."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    runtime_pb2_grpc.add_RuntimeServiceServicer_to_server(
        RuntimeServiceServicer(), server
    )
    port = "50053" # Default port for Runtime
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    logging.info(f"Runtime server started on port {port}")
    try:
        while True:
            time.sleep(86400) # Keep server running
    except KeyboardInterrupt:
        logging.info("Stopping runtime server...")
        server.stop(0)

if __name__ == "__main__":
    serve()
