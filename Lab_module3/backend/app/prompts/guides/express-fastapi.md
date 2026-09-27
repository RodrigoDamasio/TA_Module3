| Express.js                               | FastAPI                                          |
|------------------------------------------|--------------------------------------------------|
| const app = express()                    | app = FastAPI()                                  |
| app.get("/x", (req, res) => ...)         | @app.get("/x") def x(): ...                      |
| express.Router() + app.use("/p", router) | APIRouter(prefix="/p") + app.include_router(router) |
| "/users/:id"                             | "/users/{id}" + id parameter                     |
| req.body (with express.json())           | a Pydantic model parameter                       |
| req.query.q / req.params.id              | query parameter / path parameter                 |
| res.status(201).json(obj)                | return obj + status_code=201 on the decorator    |
| return res.status(404).json({error})     | raise HTTPException(status_code=404, detail=...) |
| async handler + await                    | async def handler (or def for sync work)         |
| bcryptjs / jsonwebtoken                  | bcrypt / PyJWT (jwt.encode(..., algorithm="HS256")) |
| process.env.X                            | os.environ["X"]                                  |
| app.listen(3000)                         | remove (run with uvicorn main:app)               |
