import unittest

from app.state import ActualState, can_transition


class StateMachineTest(unittest.TestCase):
    def test_pending_can_move_to_provisioning(self) -> None:
        self.assertTrue(can_transition(ActualState.PENDING, ActualState.PROVISIONING))

    def test_deleted_is_terminal(self) -> None:
        self.assertFalse(can_transition(ActualState.DELETED, ActualState.RUNNING))


if __name__ == "__main__":
    unittest.main()

