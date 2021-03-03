# make_ssh_config

`make_ssh_config` generates `ssh_config` with YAML.

The YAML input consists of a list of layers.

- A layer may be referenced later by its `name` attribute.
- Previously defined layers can be reused by listing their names in the `merge` attribute.
- SSH config is described in the `config` attribute.
- `host` attribute is a host str, or a list of host str.
- `match` attribute is a mapping of [Match][1] keywords to their values.
- Only layers with either `host` or `match` attribute are rendered to the output.
- Find about variable usage in the source code. 😀

[1]: https://manpages.debian.org/stable/openssh-client/ssh_config.5.en.html#Match

# Usage

Install the dependencies:

```bash
pipenv sync
```

By default, the input is read from `config.yaml` and the generated `ssh_config` is printed to stdout.

```bash
pipenv run make_ssh_config

# pipenv run make_ssh_config ~/.ssh/config.yaml > ~/.ssh/config # use with care
```

Find the usage with

```bash
pipenv run make_ssh_config --help
```

# Example

```yaml
---
- name: default
  config:
    IdentityFile:
      - ~/.ssh/id_rsa
      - ~/.ssh/id_ed25519

- name: shared_host
  config:
    HostName: ssh.example.com

- host: a.example.com
  merge: [ default, shared_host ]
  config:
    Port: 1022
    HostKeyAlias: "{{ host[0] }}"

- host: b.example.com
  merge: [ default, shared_host ]
  config:
    Port: 2022
    HostKeyAlias: "{{ host[0] }}"

- match:
    originalhost: git.example.com
    exec: ~/.ssh/check_work.py
  config:
    ProxyJump: a.example.com

- host:
    - git.example.com
    - github.com
  config:
    User: git
    RequestTTY: 'no'  # str, not bool
    IdentityFile:
      - ~/.ssh/git_rsa
      - ~/.ssh/git_ed255519

```

produces

```text
Host a.example.com
    IdentityFile ~/.ssh/id_rsa
    IdentityFile ~/.ssh/id_ed25519
    HostName ssh.example.com
    Port 1022
    HostKeyAlias a.example.com

Host b.example.com
    IdentityFile ~/.ssh/id_rsa
    IdentityFile ~/.ssh/id_ed25519
    HostName ssh.example.com
    Port 2022
    HostKeyAlias b.example.com

Match originalhost git.example.com exec ~/.ssh/check_work.py
    ProxyJump a.example.com

Host git.example.com github.com
    User git
    RequestTTY no
    IdentityFile ~/.ssh/git_rsa
    IdentityFile ~/.ssh/git_ed255519

```
