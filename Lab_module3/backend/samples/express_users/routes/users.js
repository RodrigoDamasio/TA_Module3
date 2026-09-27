// User routes: register, login, profile.
const express = require("express");
const bcrypt = require("bcryptjs");
const jwt = require("jsonwebtoken");

const router = express.Router();
const users = new Map();

router.post("/register", async (req, res) => {
  const { email, password, name } = req.body;
  if (!email || !password) {
    return res.status(400).json({ error: "Email and password required" });
  }
  if (users.has(email)) {
    return res.status(400).json({ error: "Email already registered" });
  }
  const hash = await bcrypt.hash(password, 10);
  users.set(email, { email, name, password: hash });
  res.status(201).json({ email, name });
});

router.post("/login", async (req, res) => {
  const { email, password } = req.body;
  const user = users.get(email);
  if (!user || !(await bcrypt.compare(password, user.password))) {
    return res.status(401).json({ error: "Invalid credentials" });
  }
  const token = jwt.sign({ email }, process.env.JWT_SECRET, { expiresIn: "7d" });
  res.json({ token });
});

router.get("/:email", (req, res) => {
  const user = users.get(req.params.email);
  if (!user) {
    return res.status(404).json({ error: "Not found" });
  }
  res.json({ email: user.email, name: user.name });
});

module.exports = router;
