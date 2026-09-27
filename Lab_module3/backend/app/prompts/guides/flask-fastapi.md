| Flask                                   | FastAPI                                         |
|-----------------------------------------|-------------------------------------------------|
| app = Flask(__name__)                   | app = FastAPI()                                 |
| @app.route("/x", methods=["POST"])      | @app.post("/x")                                 |
| <int:id> in the path                    | {id} in the path + id: int parameter            |
| request.get_json()                      | a Pydantic model parameter                      |
| request.args.get("q")                   | q: str | None = None (query parameter)          |
| return jsonify(obj), 201                | return obj + status_code=201 on the decorator   |
| abort(404)                              | raise HTTPException(status_code=404)            |
| return "", 204                          | status_code=204 + return Response(status_code=204) |
| Blueprint(url_prefix="/api")            | APIRouter(prefix="/api") + app.include_router   |
| app.run(debug=True)                     | remove (run with uvicorn main:app)              |
