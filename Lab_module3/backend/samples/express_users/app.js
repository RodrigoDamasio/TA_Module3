// User service entry point (Express).
const express = require("express");
const usersRouter = require("./routes/users");

const app = express();
app.use(express.json());

app.get("/health", (req, res) => {
  res.json({ status: "ok" });
});

app.use("/users", usersRouter);

app.listen(3000, () => console.log("Listening on 3000"));
