# /home/ubuntu/modern_simulator/models/basic_node.py
import sys
import logging
from google.protobuf.any_pb2 import Any

# Add proto directory to path to import generated code
sys.path.append("/home/ubuntu/modern_simulator/proto")

# Import generated gRPC and Protobuf files
import kernel_pb2
import model_messages_pb2

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

class BasicNodeModel:
    def __init__(self, model_id, config):
        """
        Initializes the basic node model.
        Args:
            model_id (str): Unique ID for this model instance.
            config (str): Configuration string (e.g., JSON) for this model.
        """
        self.model_id = model_id
        self.config = config # Parse config if needed
        self.logger = logging.getLogger(f"Model_{self.model_id}")
        self.logger.info(f"Initialized with config: {config}")
        self.ping_counter = 0
        self.pong_counter = 0

    def handle_event(self, current_time, event):
        """
        Handles an incoming simulation event.
        Args:
            current_time (float): The current simulation time when the event is processed.
            event (kernel_pb2.SimulationEvent): The event to handle.
        Returns:
            list[kernel_pb2.SimulationEvent]: A list of new events generated by handling this event.
        """
        self.logger.debug(f"Received event at time {current_time}: ID={event.event_id}, Target={event.target_model_id}, Source={event.source_model_id}, Data Type URL: {event.event_data.type_url}")

        generated_events = []
        event_data = None

        # Unpack event data based on type URL
        if event.event_data.Is(model_messages_pb2.PingPongData.DESCRIPTOR):
            event_data = model_messages_pb2.PingPongData()
            event.event_data.Unpack(event_data)
            self.logger.debug(f"Unpacked PingPongData: {event_data.message_content}, Seq: {event_data.sequence_number}")
        elif event.event_data.type_url == "type.googleapis.com/modern.proto.models.STARTSignal": # Match the exact case used by kernel
             self.logger.info(f"Received START signal.")
             # Send an initial PING to another node (e.g., "node_2")
             self.ping_counter += 1
             ping_payload = model_messages_pb2.PingPongData(
                 message_content="PING",
                 sequence_number=self.ping_counter
             )
             ping_any = Any()
             ping_any.Pack(ping_payload)

             ping_event = kernel_pb2.SimulationEvent(
                 timestamp=current_time + 0.1, # Send ping shortly after start
                 target_model_id="node_2", # Assume target exists
                 source_model_id=self.model_id,
                 event_data=ping_any
             )
             generated_events.append(ping_event)
             self.logger.info(f"Sent PING #{self.ping_counter} to node_2")

        else:
            self.logger.warning(f"Ignoring event with unknown data type: {event.event_data.type_url}")


        # Handle unpacked PingPongData
        if isinstance(event_data, model_messages_pb2.PingPongData):
            if event_data.message_content == "PING":
                self.logger.info(f"Received PING #{event_data.sequence_number} from {event.source_model_id}. Sending PONG.")

                # Create a PONG event to send back
                self.pong_counter += 1
                pong_payload = model_messages_pb2.PingPongData(
                    message_content="PONG",
                    sequence_number=self.pong_counter
                )
                pong_any = Any()
                pong_any.Pack(pong_payload)

                pong_event = kernel_pb2.SimulationEvent(
                    # event_id will be assigned by kernel/runtime when scheduled
                    timestamp=current_time + 1.0, # Send pong 1 time unit later
                    target_model_id=event.source_model_id, # Send back to source
                    source_model_id=self.model_id,
                    event_data=pong_any
                )
                generated_events.append(pong_event)
                self.logger.info(f"Sent PONG #{self.pong_counter} to {event.source_model_id}")

            elif event_data.message_content == "PONG":
                 self.logger.info(f"Received PONG #{event_data.sequence_number} from {event.source_model_id}.")
                 # Optionally send another PING or stop

        return generated_events

# Example usage (for testing the class structure, not for actual simulation run)
if __name__ == '__main__':
    node1 = BasicNodeModel("node_1", '{"neighbor": "node_2"}')
    node2 = BasicNodeModel("node_2", '{}')

    # Simulate receiving a START event at time 0.0
    # Create a dummy Any message for START signal
    start_any = Any()
    start_any.type_url = "type.googleapis.com/modern.proto.models.STARTSignal" # Match the exact case used by kernel

    start_event = kernel_pb2.SimulationEvent(event_id="evt_0", timestamp=0.0, target_model_id="node_1", event_data=start_any)
    generated_by_start = node1.handle_event(0.0, start_event)
    print(f"Generated by START: {[(e.timestamp, e.target_model_id, e.event_data.type_url) for e in generated_by_start]}")

    # Simulate node 2 receiving the PING event generated above
    if generated_by_start:
        ping_event = generated_by_start[0]
        generated_by_ping = node2.handle_event(ping_event.timestamp, ping_event)
        print(f"Generated by PING: {[(e.timestamp, e.target_model_id, e.event_data.type_url) for e in generated_by_ping]}")

        # Simulate node 1 receiving the PONG event generated above
        if generated_by_ping:
             pong_event = generated_by_ping[0]
             generated_by_pong = node1.handle_event(pong_event.timestamp, pong_event)
             print(f"Generated by PONG: {[(e.timestamp, e.target_model_id, e.event_data.type_url) for e in generated_by_pong]}")
