import json
import subprocess
import sys

done = subprocess.run(
    ["java", "-Xmx1g", "-jar", "/opt/tika.jar", "--text", sys.argv[1]],
    capture_output=True,
    timeout=50,
    check=True,
)
text = done.stdout.decode("utf-8", "replace")
json.dump(
    {
        "text": text[:1000000],
        "partial": len(text) > 1000000,
        "mime": json.loads(sys.argv[2])["mime"],
        "engine": "apache-tika",
        "version": "3.3.3",
    },
    sys.stdout,
)
