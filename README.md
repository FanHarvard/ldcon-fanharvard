# ldcon-fanharvard

FanHarvard laser-operation configuration for **Sr422 (ECDL), Sr1092 (DFB/DBR), and ThF685 (DLC Pro)**.
**Still in active development.** MIT licensed.

This repository contains site wiring, laser/deck settings and setup tools. Control code comes from
[ldcon](https://github.com/FanHarvard/ldcon), [experiment-core](https://github.com/FanHarvard/experiment-core), [experiment-drivers](https://github.com/FanHarvard/experiment-drivers)
and [agentbridge](https://github.com/FanHarvard/agentbridge).

```bash
git clone https://github.com/FanHarvard/ldcon-fanharvard.git
cd ldcon-fanharvard
python3.12 ops/setup.py --editable
.venv/bin/python ops/site.py init "$HOME/.local/share/ldcon-fanharvard"
```

`--editable` clones the four libraries into `libraries/` and installs them with `pip install -e`.
Edit those checkouts directly; Python changes apply on the next process start. Existing checkouts and
uncommitted changes are preserved. To use pinned releases (including the shared DHO wheel from GitHub) instead:

```bash
python3.12 ops/setup.py --published
```

Setup validates **3 lasers / 78 cards offline** and starts no services. Outputs are disabled in the
initial configuration. Runtime files and locally generated credentials stay outside Git.
The site files include FanHarvard LAN addresses and hardware identities, but no credential values.

[Operation, updates and migration](docs/operations.html) covers command/unit generation, hardware
prerequisites and switching back to editable libraries. Agents: Claude Code, Codex and OpenCode;
DeepSeek Harness is available as a task adapter. Contact: **kenjishu@fas.harvard.edu**.
