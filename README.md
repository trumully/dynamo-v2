<h2 align="center">Dynamo</h2>
<h4 align="center">My personal Discord bot</h4>
<p align="center">
<a href="" rel="noopener"><img src="assets/img/dynamo.png" alt="Dynamo" height="400"></a>
</p>

## Set up
### Prerequisites 
* Python 3.13
* uv

### Setup a venv
You should use `uv` but anything works really.
```sh
uv sync
```
Requirements specified in `pyproject.toml` / `uv.lock`

## Using
### Store bot token
You should set it in `.secrets.toml` at the root
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
> This requires `uv` to run and Node for Pyright. I recommend setting up Node with [fnm](https://github.com/Schniz/fnm)

```sh
uv run check.py
```