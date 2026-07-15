<h2 align="center">Dynamo</h2>
<h4 align="center">A personal Discord bot</h4>
<p align="center">
<a href="" rel="noopener"><img src="assets/img/dynamo.png" alt="Dynamo" height="400"></a>
</p>

## Running

Not quite ready for running yet. But, if you insist:

Python 3.14
- CPython
- Free threading support will be blocked

Assuming you have uv
```bash
uv sync
uv run dynamo --setup
uv run dynamo
```

Install requirements listed in `pyproject.toml` manually. Entrypoint is `src/dynamo/cli.py`
