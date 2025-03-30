<h2 align="center">Dynamo</h2>
<p align="center">
<a href="" rel="noopener"><img src="assets/img/dynamo.png" alt="Dynamo" height="400"></a>
</p>

## Set up
### Preqrequisites 
```sh
winget add --id Python.Python.3.13 -e
winget add --id astral-sh.uv -e
```

### Clone repository
```sh
git clone https://github.com/trumully/dynamo-v2.git
```

### Sync
```sh
cd dynamo
uv sync
```

## Using
### Check
```sh
uv run build.py --check
```

### Run
Entrypoint is in `dynamo/cli.py`. You can run with Python with a virtual environment (probably better) or with uv (easier).

```sh
uv run dynamo
```

```sh
# replace `py` with whatever alias your system uses
py -O dynamo/cli.py
```