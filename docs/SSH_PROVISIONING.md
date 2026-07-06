# SSH Provisioning

SSH provisioning is the next step after local Docker provisioning. Instead of creating containers on the same machine as the API and worker, the worker connects to a remote Linux host and runs a controlled provisioning command there.

## Mental Model

```text
Browser
  -> API
  -> Postgres resource + job
  -> Worker
  -> SSH connection
  -> Remote VPS
  -> Controlled remote script
  -> Docker container / game server
  -> Database updated with URL and external ID
```

The API still does not SSH anywhere. It only records intent and queues a job. The worker owns SSH because remote provisioning can be slow, fail halfway through, or need retries.

## Why SSH Provisioning Matters

SSH provisioning teaches real DevOps skills:

- SSH keys
- non-root remote users
- remote command execution
- command quoting
- timeouts
- host key checking
- idempotent scripts
- remote Docker management
- logs and cleanup

## Safety Rule

Users should never type arbitrary shell commands.

The app should only let users choose from approved templates. The worker then turns those templates into controlled remote commands.

Good:

```text
tiny-provisioner-remote provision --slug demo --image tiny-python-http-app:local
```

Bad:

```text
run whatever command the user typed
```

## Current First Slice

The first SSH backend adds:

- `PROVISIONER_BACKEND=ssh`
- SSH host/user/key settings
- an `SSHProvisioner` class
- fixed remote command generation
- SSH batch mode
- strict host key checking by default
- timeout handling
- tests that prove command shape and factory wiring
- a remote command implementation in `scripts/tiny_provisioner_remote.py`
- a wrapper named `scripts/tiny-provisioner-remote`

This first slice does not require a real VPS to test. The tests verify how the worker would call SSH and how the remote script would call Docker.

## Environment Variables

```text
PROVISIONER_BACKEND=ssh
SSH_HOST=your-vps.example.com
SSH_USER=provisioner
SSH_KEY_PATH=/run/secrets/tiny_provisioner_ssh_key
SSH_PORT=22
SSH_REMOTE_COMMAND=tiny-provisioner-remote
SSH_TIMEOUT_SECONDS=60
SSH_STRICT_HOST_KEY_CHECKING=true
```

## Remote Host Plan

The remote server should eventually have:

- a dedicated `provisioner` Linux user
- SSH key login only
- no root SSH login
- Docker installed
- firewall rules for SSH, HTTP, and HTTPS
- a controlled script at `/usr/local/bin/tiny-provisioner-remote`

## Game Server Note

The current portfolio game template is an HTTP browser game, so it fits the existing Traefik HTTP routing model.

Traditional game servers such as Minetest usually use UDP. That is a separate networking milestone because UDP game traffic needs different routing/firewall behavior than the current HTTP reverse-proxy flow.

## Remote Script Shape

The repo now includes a remote script that supports actions like:

```text
tiny-provisioner-remote provision --resource-id 7 --slug demo --image minetest:local --exposed-port 30000 --cpu-limit 1 --memory-mb 512
tiny-provisioner-remote stop --external-id ssh:vps.example.com:demo
tiny-provisioner-remote start --external-id ssh:vps.example.com:demo
tiny-provisioner-remote delete --external-id ssh:vps.example.com:demo
tiny-provisioner-remote logs --external-id ssh:vps.example.com:demo --tail 100
```

The script should be idempotent. Running `delete` twice should be safe. Running `provision` twice for the same slug should not create duplicate containers.

Current idempotent behavior:

- `provision` creates a container if missing.
- `provision` starts an existing stopped container.
- `provision` does nothing dangerous if the container is already running.
- `delete` removes the container if present.
- `delete` succeeds if the container is already gone.
- `logs` returns a friendly message if the container no longer exists.

## Local Script Tests

The script is tested without touching a real Docker daemon:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_remote_script.py
```

Those tests use a fake Docker runner to prove command shape and safe repeat behavior.

## Manual Remote Install Plan

On a real VPS, install the script under the command name the worker expects:

```bash
sudo install -m 0755 scripts/tiny_provisioner_remote.py /usr/local/bin/tiny-provisioner-remote
```

Then test a harmless action after Docker is installed:

```bash
tiny-provisioner-remote logs --external-id ssh:vps.example.com:missing-demo
```

Expected result:

```text
Container logs are unavailable because the container no longer exists.
```

Do not point the app at a VPS until SSH key login, Docker, firewall rules, and the remote script are all tested directly.

## Interview Explanation

Use this:

> I added an SSH provisioner so the worker can provision on a remote Linux host instead of only using local Docker. The API still only records desired state and queues jobs. The worker uses an SSH key to call a controlled remote script. This keeps slow and sensitive infrastructure work out of the request path, prevents arbitrary user commands, and models how a small control plane could manage a VPS.

## Flashcards

Q: Why should the API not SSH directly?

A: SSH provisioning is slow and sensitive. The worker is better for timeouts, retries, logs, and limiting which service touches SSH keys.

Q: Why should users not provide shell commands?

A: That would be remote code execution by design. Users should choose approved templates instead.

Q: What does host key checking protect against?

A: It helps verify that the worker is connecting to the expected server, not an impostor.

Q: Why use a dedicated remote user?

A: It limits blast radius. The provisioning process should not need full root SSH access.

Q: What is the first thing to test?

A: A harmless controlled command, then remote Docker provisioning after the SSH path is proven.
