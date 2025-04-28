<h2 align="center">Dynamo</h2>
<h4 align="center">My personal Discord bot</h4>
<p align="center">
<a href="" rel="noopener"><img src="assets/img/dynamo.png" alt="Dynamo" height="400"></a>
</p>

## Set up
### Prerequisites 
* [Python 3.13](https://www.python.org/downloads/)
* [uv](https://docs.astral.sh/uv/getting-started/installation/) (optional)

> [!TIP]
> If you use `uv`, it will [download Python versions when they are required](https://docs.astral.sh/uv/guides/install-python/#automatic-python-downloads)

### Setup a venv
Assuming you are using `uv`
```sh
uv sync
```
Requirements specified in `pyproject.toml` / `uv.lock`

## Using
### Store bot token
Assign in `.secrets.toml`
```toml
# .secrets.toml
token = "your token here"
```
Alternatively, you can set the environment variable `DYNAMO_TOKEN`

### Run
Entry point is `dynamo/cli.py`.
```sh
uv run dynamo
```

### Check lint/format/typing
> [!NOTE]
> This requires `uv` to run and Node for Pyright. I recommend setting up Node with [Volta](https://volta.sh/)

```sh
uv run check.py
```