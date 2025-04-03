<h2 align="center">Dynamo</h2>
<p align="center">
<a href="" rel="noopener"><img src="assets/img/dynamo.png" alt="Dynamo" height="400"></a>
</p>

## Set up
### Preqrequisites 
```pwsh
winget add --id Python.Python.3.13 -e
winget add --id astral-sh.uv -e
```

### Clone repository
```pwsh
git clone https://github.com/trumully/dynamo-v2.git
```

### Sync
```pwsh
cd dynamo
uv sync
```

## Using
### Check
```pwsh
uv run build.py --check
```

### Run
```pwsh
uv run dynamo
```