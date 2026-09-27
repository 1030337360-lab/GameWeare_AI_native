"""Build the self-contained Java interview game from its verified v3 base and curated questions."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "content" / "java-interview-quiz"
base = (CONTENT / "base-v3.html").read_text(encoding="utf-8")
questions = json.loads((CONTENT / "additional-questions.json").read_text(encoding="utf-8"))
topics = ["基础与集合", "反射与代理", "异常与拷贝", "字符串与Java8", "并发与JMM", "线程池", "锁与AQS", "JVM与IO"]

assert len(questions) == 64, f"Expected 64 additions, got {len(questions)}"
assert len({question["q"] for question in questions}) == len(questions), "Duplicate question"
for question in questions:
    assert question["topic"] in topics
    assert question["level"] in {"基础", "进阶"}
    assert len(question["o"]) == 4 and len(set(question["o"])) == 4
    assert 0 <= question["a"] < 4 and question["e"].strip()
for topic in topics[1:]:
    assert sum(q["topic"] == topic and q["level"] == "基础" for q in questions) >= 1
    assert sum(q["topic"] == topic and q["level"] == "进阶" for q in questions) >= 1


def replace_once(old: str, new: str) -> None:
    global base
    assert base.count(old) == 1, f"Expected one occurrence of {old[:70]!r}; got {base.count(old)}"
    base = base.replace(old, new)


addition = json.dumps(questions, ensure_ascii=False, separators=(",", ":"))
topic_list = json.dumps(topics, ensure_ascii=False, separators=(",", ":"))
replace_once(
    "var LIMIT=22,ROUND=10;",
    "POOL.forEach(function(q){q.topic='基础与集合';q.level='基础'});\n"
    + "POOL=POOL.concat(" + addition + ");\n"
    + "var TOPICS=" + topic_list + ";\n"
    + "var LIMIT=22,ROUND=16;",
)
replace_once(
    "function start(){",
    "function selectQuestions(){\n"
    "  var chosen=[];\n"
    "  TOPICS.forEach(function(topic){\n"
    "    ['基础','进阶'].forEach(function(level){\n"
    "      var candidates=POOL.filter(function(q){return q.topic===topic&&q.level===level});\n"
    "      chosen.push(shuffle(candidates)[0]);\n"
    "    });\n"
    "  });\n"
    "  return shuffle(chosen).map(build);\n"
    "}\n"
    "function start(){",
)
replace_once("deck=shuffle(POOL.slice()).slice(0,ROUND).map(build);", "deck=selectQuestions();")
replace_once(
    "return{q:q.q,o:ps.map(function(p){return p.t}),a:k,e:q.e,done:false,pick:null,gain:0,st:0,left:LIMIT};",
    "return{q:q.q,o:ps.map(function(p){return p.t}),a:k,e:q.e,topic:q.topic,level:q.level,done:false,pick:null,gain:0,st:0,left:LIMIT};",
)
replace_once(
    '$("h5").textContent=q.done?"已作答 · 点编号可切回":"知识点 "+(idx+1)+" · 词语识别";',
    '$("h5").textContent=q.done?"已作答 · 点编号可切回":q.topic+" · "+q.level;',
)
replace_once("随机抽 <b>10 题</b>", "按 8 个方向抽取 <b>16 题</b>（每方向基础、进阶各 1 题）")
replace_once("🥉 需要重读讲义第一二三节", "🥉 基础还需巩固")
replace_once(
    '  $("e3").innerHTML="本轮答对 <b>"+right+',
    '  var weak=[];deck.forEach(function(d){if(!d.done||d.pick!==d.a){if(weak.indexOf(d.topic)<0)weak.push(d.topic)}});\n'
    '  $("e3").innerHTML="本轮答对 <b>"+right+',
)
replace_once(
    '重点复习：包装类缓存、equals/hashCode 契约、HashMap 扩容与树化、LinkedHashMap 与 LRU、fail-fast 与并发集合。";',
    '重点复习："+(weak.length?weak.join("、"):"无，继续挑战进阶题")+"。";\n'
    '  $("e3").innerHTML+="<br>分方向："+TOPICS.map(function(topic){'
    'var items=deck.filter(function(d){return d.topic===topic});'
    'var correct=items.filter(function(d){return d.done&&d.pick===d.a}).length;'
    'return topic+" "+correct+"/2";}).join(" · ");',
)

output = CONTENT / "index.html"
output.write_text(base, encoding="utf-8")
print(f"Built {output}: 16 original + {len(questions)} new = {16 + len(questions)} questions, 16 per round")
