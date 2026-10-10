import uvicorn

from app.config import HOST, PORT


def main() -> None:
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    main()
