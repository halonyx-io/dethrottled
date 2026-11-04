"""Read-only host/runtime inventory; excludes environment variables and addresses."""
import json
import os
import platform
import shutil
import subprocess
import sys
import time


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    return dict(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)


ids = run('docker', 'ps', '-q', '--filter',
          'label=com.docker.compose.project=dethrottled-benchmark')['stdout'].split()
images = set()
containers = []
for container in ids:
    value = json.loads(run('docker', 'inspect', container)['stdout'])[0]
    images.add(value['Image'])
    containers.append({
        'service': value['Config']['Labels']['com.docker.compose.service'],
        'image_id': value['Image'], 'memory_limit': value['HostConfig']['Memory'],
        'nano_cpus': value['HostConfig']['NanoCpus'], 'state': value['State']['Status'],
        'gpu_devices': value['HostConfig'].get('Devices', []),
    })
record = dict(timestamp=time.time(), architecture=platform.machine(), kernel=platform.release(),
              python=sys.version, cpus=os.cpu_count(), load=os.getloadavg(),
              os_release=run('cat', '/etc/os-release'), cpu=run('lscpu'),
              memory=run('free', '-b'), filesystem=shutil.disk_usage('/')._asdict(),
              docker=run('docker', 'version'), compose=run('docker', 'compose', 'version'),
              image_disk=run('docker', 'system', 'df'), containers=containers,
              images=[{k: v.get(k) for k in ('Id', 'RepoTags', 'Architecture', 'Size')}
                      for image in sorted(images)
                      for v in json.loads(run('docker', 'image', 'inspect', image)['stdout'])])
print(json.dumps(record, indent=2))
