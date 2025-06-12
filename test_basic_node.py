import unittest
import sys
import os
from unittest.mock import MagicMock, patch

# Add proto and models directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'proto')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'models')))

from models.basic_node import BasicNodeModel
import kernel_pb2
import model_messages_pb2
import shared_messages_pb2
from google.protobuf.any_pb2 import Any

class TestBasicNodeModel(unittest.TestCase):

    def setUp(self):
        self.model_id = "test_node"
        self.config = "{}"
        self.basic_node = BasicNodeModel(self.model_id, self.config)

    def test_initialization(self):
        self.assertEqual(self.basic_node.model_id, self.model_id)
        self.assertEqual(self.basic_node.config, self.config)
        self.assertEqual(self.basic_node.ping_counter, 0)
        self.assertEqual(self.basic_node.pong_counter, 0)

    def test_handle_start_event(self):
        current_time = 0.0
        start_any = Any()
        start_any.Pack(model_messages_pb2.STARTSignal())
        start_event = shared_messages_pb2.SimulationEvent(
            event_id="evt_start",
            timestamp=current_time,
            target_model_id=self.model_id,
            source_model_id="KERNEL_INIT",
            event_data=start_any
        )

        generated_events = self.basic_node.handle_event(current_time, start_event)

        self.assertEqual(self.basic_node.ping_counter, 1)
        self.assertEqual(len(generated_events), 1)
        self.assertEqual(generated_events[0].timestamp, current_time + 0.1)
        self.assertEqual(generated_events[0].target_model_id, "node_2")
        self.assertEqual(generated_events[0].source_model_id, self.model_id)
        self.assertTrue(generated_events[0].event_data.Is(model_messages_pb2.PingPongData.DESCRIPTOR))

        ping_data = model_messages_pb2.PingPongData()
        generated_events[0].event_data.Unpack(ping_data)
        self.assertEqual(ping_data.message_content, "PING")
        self.assertEqual(ping_data.sequence_number, 1)

    def test_handle_ping_event(self):
        current_time = 0.5
        ping_payload = model_messages_pb2.PingPongData(
            message_content="PING",
            sequence_number=5
        )
        ping_any = Any()
        ping_any.Pack(ping_payload)
        ping_event = shared_messages_pb2.SimulationEvent(
            event_id="evt_ping",
            timestamp=current_time,
            target_model_id=self.model_id,
            source_model_id="node_1",
            event_data=ping_any
        )

        generated_events = self.basic_node.handle_event(current_time, ping_event)

        self.assertEqual(self.basic_node.pong_counter, 1)
        self.assertEqual(len(generated_events), 1)
        self.assertEqual(generated_events[0].timestamp, current_time + 1.0)
        self.assertEqual(generated_events[0].target_model_id, "node_1")
        self.assertEqual(generated_events[0].source_model_id, self.model_id)
        self.assertTrue(generated_events[0].event_data.Is(model_messages_pb2.PingPongData.DESCRIPTOR))

        pong_data = model_messages_pb2.PingPongData()
        generated_events[0].event_data.Unpack(pong_data)
        self.assertEqual(pong_data.message_content, "PONG")
        self.assertEqual(pong_data.sequence_number, 1)

    def test_handle_pong_event(self):
        current_time = 1.5
        pong_payload = model_messages_pb2.PingPongData(
            message_content="PONG",
            sequence_number=1
        )
        pong_any = Any()
        pong_any.Pack(pong_payload)
        pong_event = shared_messages_pb2.SimulationEvent(
            event_id="evt_pong",
            timestamp=current_time,
            target_model_id=self.model_id,
            source_model_id="node_1",
            event_data=pong_any
        )

        generated_events = self.basic_node.handle_event(current_time, pong_event)

        self.assertEqual(len(generated_events), 0)

    def test_handle_unknown_event(self):
        current_time = 0.0
        unknown_any = Any()
        unknown_any.type_url = "type.googleapis.com/unknown.EventType"
        unknown_event = shared_messages_pb2.SimulationEvent(
            event_id="evt_unknown",
            timestamp=current_time,
            target_model_id=self.model_id,
            source_model_id="EXTERNAL",
            event_data=unknown_any
        )

        generated_events = self.basic_node.handle_event(current_time, unknown_event)

        self.assertEqual(len(generated_events), 0)

if __name__ == '__main__':
    unittest.main()

