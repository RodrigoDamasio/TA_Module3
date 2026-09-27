from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()
ARTICLES = {1: {"id": 1, "title": "Hello", "body": "First post"}}


class ArticleIn(BaseModel):
    title: str
    body: str = ""


@app.get("/articles")
def list_articles() -> dict:
    return {"articles": list(ARTICLES.values())}


@app.get("/articles/{pk}")
def article_detail(pk: int) -> dict:
    article = ARTICLES.get(pk)
    if article is None:
        raise HTTPException(status_code=404, detail="Not found")
    return article


@app.post("/articles/new", status_code=201)
def create_article(body: ArticleIn) -> dict:
    new_id = max(ARTICLES) + 1
    ARTICLES[new_id] = {"id": new_id, "title": body.title, "body": body.body}
    return ARTICLES[new_id]
