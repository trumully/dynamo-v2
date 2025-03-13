# Dynamo 

## Setup
### Install Python 3.13
```sh
winget install --id Python.Python.3.13 --exact
```
### Install uv
```sh
winget install --id astral-sh.uv --exact
```

### Clone repository
```sh
git clone https://github.com/trumully/dynamo-v2.git
```

### Sync
```sh
cd dynmao
uv sync
```

## Run
```sh
uv run dynamo
```