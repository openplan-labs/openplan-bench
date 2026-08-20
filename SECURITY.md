# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.1.x   | Yes       |

## Threat model

openplan-bench opens no network connections at run time. It does two things
worth thinking about:

- **It executes planner code in subprocesses.** Every measurement runs
  `python -m openplan_bench.worker` in a child process, with a wall-clock kill
  and an `RLIMIT_AS` ceiling. That sandbox exists to keep a wedged planner from
  taking down a sweep — it is **not** a security boundary and must not be
  treated as one. Do not point a suite at a planner you would not run directly.
- **It reads suite files and PDDL corpora from disk.** A suite is parsed with
  `yaml.safe_load`, so a malicious suite cannot construct arbitrary Python
  objects. It can, however, name any adapter and any file path on the machine.
  Treat a suite file from a stranger the way you would treat a shell script.

The generated dashboard is static HTML with no external requests and no
user-supplied script; values from results files are HTML-escaped on the way in.

## Reporting a vulnerability

If you believe you have found a security issue — an escape from the worker
sandbox, an injection through a results file into the generated site, or a path
traversal through a suite's `corpus_root` — please report it privately:

- Email **erwin.lejeune15@gmail.com** with a description, a minimal
  reproduction, and the affected version.
- Or use GitHub's private vulnerability reporting on this repository
  (Security → Report a vulnerability).

You will get an acknowledgement within a week. Please do not open a public
issue for a suspected vulnerability before a fix is released.
