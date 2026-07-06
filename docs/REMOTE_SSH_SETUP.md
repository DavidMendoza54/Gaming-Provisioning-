# Remote SSH Provisioning Setup

This runbook is for the SSH provisioning model:

```text
TinyProvisioner control plane -> SSH -> remote VPS -> Docker workload
```

Use this after the local Docker backend works and before pointing `PROVISIONER_BACKEND=ssh` at a real server.

## What You Are Building

The remote VPS is not the public control panel. It is a target machine where the worker can create containers through SSH.

The control plane still owns:

- users
- auth
- resources
- jobs
- events
- system status

The remote VPS owns:

- Docker
- provisioned workload containers
- the `tiny-provisioner-remote` script

## Safety Goals

- Do not SSH as `root` for provisioning.
- Use a dedicated `provisioner` Linux user.
- Use SSH keys, not passwords.
- Keep user input out of shell commands.
- Run only the controlled `tiny-provisioner-remote` script.
- Test SSH manually before the app uses it.

## 1. Create An SSH Key Locally

On your workstation:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/tiny_provisioner_vps -C "tiny-provisioner"
```

This creates:

```text
~/.ssh/tiny_provisioner_vps
~/.ssh/tiny_provisioner_vps.pub
```

The `.pub` file is safe to copy to the VPS. The private key is sensitive.

## 2. Create A Dedicated User On The VPS

SSH into the VPS with your normal admin account first, then:

```bash
sudo adduser --disabled-password --gecos "" provisioner
sudo usermod -aG docker provisioner
```

Why:

- `provisioner` is easier to audit than root.
- Access can be removed without deleting your admin account.
- The blast radius is smaller if the provisioning path has a bug.

## 3. Install The Public Key

Replace the example key with the contents of `~/.ssh/tiny_provisioner_vps.pub`:

```bash
sudo install -d -m 700 -o provisioner -g provisioner /home/provisioner/.ssh
echo "ssh-ed25519 REPLACE_WITH_PUBLIC_KEY tiny-provisioner" | sudo tee /home/provisioner/.ssh/authorized_keys
sudo chown provisioner:provisioner /home/provisioner/.ssh/authorized_keys
sudo chmod 600 /home/provisioner/.ssh/authorized_keys
```

Test from your workstation:

```bash
ssh -i ~/.ssh/tiny_provisioner_vps provisioner@YOUR_VPS_HOSTNAME "whoami"
```

Expected:

```text
provisioner
```

## 4. Install Docker On The VPS

Install Docker using the official Docker instructions for your VPS operating system.

Then verify:

```bash
docker version
docker run --rm hello-world
```

If `provisioner` was added to the Docker group after login, log out and back in before testing Docker as that user:

```bash
ssh -i ~/.ssh/tiny_provisioner_vps provisioner@YOUR_VPS_HOSTNAME "docker ps"
```

## 5. Copy The Remote Script

From your project folder on your workstation:

```bash
scp -i ~/.ssh/tiny_provisioner_vps scripts/tiny_provisioner_remote.py provisioner@YOUR_VPS_HOSTNAME:/tmp/tiny_provisioner_remote.py
```

Then on the VPS:

```bash
sudo install -m 0755 /tmp/tiny_provisioner_remote.py /usr/local/bin/tiny-provisioner-remote
```

Or, if the repo is already cloned on the VPS:

```bash
sudo scripts/install_remote_provisioner.sh
```

## 6. Test The Remote Script Directly

Run this on the VPS:

```bash
tiny-provisioner-remote logs --external-id ssh:localhost:missing-demo
```

Expected:

```text
Container logs are unavailable because the container no longer exists.
```

This proves the script can run and handle a safe missing-container case.

## 7. Test SSH To The Remote Script

Run this from your workstation:

```bash
ssh -i ~/.ssh/tiny_provisioner_vps provisioner@YOUR_VPS_HOSTNAME \
  "tiny-provisioner-remote logs --external-id ssh:YOUR_VPS_HOSTNAME:missing-demo"
```

Expected:

```text
Container logs are unavailable because the container no longer exists.
```

This proves the worker's future SSH path has the right shape.

## 8. Configure TinyProvisioner

When ready, set:

```text
PROVISIONER_BACKEND=ssh
SSH_HOST=YOUR_VPS_HOSTNAME
SSH_USER=provisioner
SSH_KEY_PATH=/path/inside/worker/container/to/private/key
SSH_PORT=22
SSH_REMOTE_COMMAND=tiny-provisioner-remote
SSH_TIMEOUT_SECONDS=60
SSH_STRICT_HOST_KEY_CHECKING=true
```

Do not store the private key in Git.

## 9. Lock Down SSH After Testing

Only after key login works, consider disabling password login and root login.

Create a file such as:

```bash
sudo nano /etc/ssh/sshd_config.d/tiny-provisioner.conf
```

Example:

```text
PasswordAuthentication no
PermitRootLogin no
```

Then validate and reload:

```bash
sudo sshd -t
sudo systemctl reload ssh
```

Keep an existing admin SSH session open while testing the new settings so you do not lock yourself out.

## Interview Explanation

Use this:

> For SSH provisioning, I use a dedicated remote `provisioner` user and key-based authentication. The worker connects over SSH and runs one controlled script instead of arbitrary shell commands. That reduces blast radius, keeps the API out of SSH, and makes provisioning easier to audit and test.

## Flashcards

Q: Why not SSH as root?

A: Root increases blast radius. A dedicated user limits and isolates the provisioning path.

Q: Why test SSH manually first?

A: It separates infrastructure setup problems from application bugs.

Q: Why keep the private key out of Git?

A: Anyone with the private key can authenticate as the provisioner user.

Q: Why run one controlled remote script?

A: It avoids remote code execution by design and keeps command behavior testable.
