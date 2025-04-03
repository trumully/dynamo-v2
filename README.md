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

### Setup virtual environment
You can easily set this up with `uv` but feel free to set it up however you prefer. Requirements are in `pyproject.toml`
```sh
uv sync
```

## Using
### Check lint/format/typing
```sh
uv run build.py --check
```

### Store bot token
You *can* set the environment variable `DYNAMO_TOKEN` but you *should* set it in `.secrets.toml` at the root:
```toml
token = "your token here"
```

### Run
Entry point is `dynamo/cli.py`. You can run this directly with Python if you prefer.
```sh
uv run dynamo
```