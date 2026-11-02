"""Offline wiring check: exercise the installed site DHO adapter without a network."""
from unittest.mock import patch

from experiment_drivers.oscilloscopes.rigol_dho import RigolDHO
from ldcon.drivers.rigol_scope import RigolScope


def main():
    with patch("socket.create_connection", side_effect=AssertionError("Unexpected I/O")), \
         patch.object(RigolDHO, "read_snapshot", autospec=True, return_value={"trigger_status": "WAIT"}) as read:
        scope = RigolScope("unused.example", 5555, "synthetic", "TEST")
        assert scope.read() == {"trigger_status": "WAIT"}, "Installed ldcon must use experiment-drivers for DHO"
        read.assert_called_once_with(scope)
        assert scope.expected_model == "DHO924" and scope.expected_serial == "TEST"
        scope.close()
    print("RIGOL DHO: site ldcon adapter delegates to installed experiment-drivers (offline).")


if __name__ == "__main__":
    main()
