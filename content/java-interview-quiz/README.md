# Java 面试词霸题库

- `base-v3.html`：修复了初始页面不可见问题后的原始 16 题游戏。
- `additional-questions.json`：参考用户提供的 Java SE、集合、线程池、AQS、锁与反射等资料整理的 64 道新题。重复的线程池附件只采纳一次；题目按 Java 8 语境核对，避免把讲义中的经验说法当成无条件规则。
- `index.html`：运行 `python scripts/build-java-interview-quiz.py` 生成的单文件游戏，包含 80 道题。每局从八个方向各抽一题基础题、一题进阶题，共 16 题。

新增题目包含 `topic`、`level`、题干、四个选项、正确选项索引和解析。修改题目后重新运行构建脚本；脚本会检查数量、重复题干、选项和各方向难度覆盖。
