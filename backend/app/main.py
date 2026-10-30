from fastapi import FastAPI

app = FastAPI(title="Event Registration API")


@app.get("/health")
def health_check():
    return {"status": "ok"}
