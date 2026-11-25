import os
import sys
from tempfile import TemporaryDirectory

from temworkbench.cli import main

with TemporaryDirectory(prefix="temworkbench-browser-") as data:
    os.environ["TEMWORKBENCH_OPERATOR_TOKEN"] = "browser-test-operator"
    os.environ["TEMWORKBENCH_AGENT_TOKEN"] = "browser-test-agent"
    sys.argv = ["temworkbench", "--port", "18765", "--data", data]
    main()
