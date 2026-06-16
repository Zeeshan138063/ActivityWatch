# Git Repository Setup

## Remotes

| Name | URL | Purpose |
|------|-----|---------|
| `origin` | `git@github.com:Zeeshan138063/ActivityWatch.git` | PCD fork — push changes here |
| `upstream` | `https://github.com/ActivityWatch/activitywatch.git` | Original ActivityWatch OSS repo |

## Push to your fork

```bash
git push -u origin master
```

## Pull upstream ActivityWatch updates

```bash
git fetch upstream
git merge upstream/master
```

## Submodules

This repo uses git submodules. After cloning, initialise them with:

```bash
git submodule update --init --recursive
```

To update all submodules to their latest tracked commits:

```bash
git submodule update --remote
```
