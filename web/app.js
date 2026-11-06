(function () {
  var S = { sid: "", mock: false, profile: null, artifacts: {}, busy: false,
    tab: (function () { try { var t = new URLSearchParams(location.search).get("tab"); return (t === "compliance" || t === "policy") ? t : "listing"; } catch (e) { return "listing"; } })() };
  var $ = function (id) { return document.getElementById(id); };

  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function post(path, body) {
    var ctl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctl) ctl.abort(); }, 100000);
    var opt = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    };
    if (ctl) opt.signal = ctl.signal;
    return fetch(path, opt).then(function (r) {
      clearTimeout(timer);
      if (r.status === 401) { location.replace("/login"); throw new Error("口令已过期"); }
      return r.json();
    }, function (e) {
      clearTimeout(timer);
      throw new Error(e && e.name === "AbortError" ? "请求超时（100 秒）" : (e.message || "网络错误"));
    });
  }
  function get(path) { return fetch(path).then(function (r) { return r.json(); }); }

  function addMsg(role, text) {
    var box = $("msgs");
    var d = document.createElement("div");
    d.className = "msg " + (role === "user" ? "user" : "bot");
    var who = role === "user" ? "我" : "参";
    d.innerHTML = '<div class="who">' + who + '</div><div class="bubble">' + esc(text) + "</div>";
    box.appendChild(d);
    box.scrollTop = box.scrollHeight;
    return d;
  }

  function typing() {
    var d = addMsg("bot", "正在处理…");
    d.querySelector(".bubble").classList.add("typing");
    return d;
  }

  function setChips(list) {
    var box = $("chips");
    box.innerHTML = "";
    if (!list || !list.length) return;
    list.forEach(function (c) {
      var b = document.createElement("button");
      b.className = "chip";
      b.type = "button";
      b.textContent = c;
      b.onclick = function () { send(c); };
      box.appendChild(b);
    });
  }

  function greet() {
    addMsg("bot", "我是厂长参谋。给我一张产品照片，或者一句话说清你做什么、想卖到哪里，我来判断合规、写 listing、顺便查一下能申报的政策。");
    setChips([
      "我做碳纤维自行车车架，想卖到欧盟",
      "我们做手工羊毛地毯，出口美国",
      "五金铰链，主要给德国客户"
    ]);
  }

  function apply(d, silent) {
    if (!d || d.ok === false) { addMsg("bot", "出错了：" + ((d && d.error) || "未知错误")); return; }
    S.mock = !!d.mock;
    if (d.state) $("stateTag").textContent = ({ new: "待建档", clarify: "待确认", done: "已出方案" })[d.state] || d.state;
    $("modeTag").textContent = S.mock ? "样例模式" : "已接入模型";
    $("modeTag").className = "tag " + (S.mock ? "tag-mock" : "tag-live");
    if (d.profile) { S.profile = d.profile; renderProfile(); }
    if (d.artifacts) { S.artifacts = d.artifacts; renderTab(); }
    if (d.reply) {
      var node = addMsg("bot", d.reply);
      if (d.questions && d.questions.length) renderQuestions(d.questions, node);
    }
    if (silent && (!d.messages || !d.messages.length)) greet();
  }

  function renderQuestions(qs, anchor) {
    var wrap = document.createElement("div");
    wrap.className = "qwrap";
    qs.forEach(function (q) {
      if (!q.options || !q.options.length) return;
      var cap = document.createElement("div");
      cap.className = "qlabel";
      cap.textContent = q.label || q.text || "";
      wrap.appendChild(cap);
      var line = document.createElement("div");
      line.className = "chips-inline";
      q.options.forEach(function (o) {
        var b = document.createElement("button");
        b.className = "chip";
        b.type = "button";
        b.textContent = o.label;
        b.onclick = function () { send(o.label); };
        line.appendChild(b);
      });
      wrap.appendChild(line);
    });
    if (wrap.children.length) {
      anchor.querySelector(".bubble").appendChild(wrap);
      $("msgs").scrollTop = $("msgs").scrollHeight;
    }
  }

  function specLine(prod) {
    var s = (prod && prod.specs) || {};
    var map = { size: "尺寸", weight: "重量", moq: "起订量", lead_time: "交期" };
    var parts = [];
    ["size", "weight", "moq", "lead_time"].forEach(function (k) {
      if (s[k]) parts.push(map[k] + " " + s[k]);
    });
    return parts.length ? parts.join("　") : "未填写（不影响合规判断，只是 listing 里不会写规格）";
  }

  var CAT_NAMES = {
    bike: "自行车及配件", carpet: "地毯及铺地材料", hardware: "五金件",
    appliance: "家电与电器", apparel: "服装与家纺", toy: "玩具与婴童用品",
    lighting: "灯具与照明", furniture: "家具", foodware: "食品接触与厨具",
    cosmetics: "化妆品", auto: "汽车配件", medical: "医疗器械", other: "其他"
  };

  // 标准与法规（16 CFR、EN、ISO、GPSR、CPSIA）不是「持有的认证」，CE/UKCA/UL 才是。
  // 混在一起显示，档案里会写成「已有认证：GPSR」——评委一眼看出这是外行。
  function splitCerts(p) {
    var meta = p.certs_meta || {};
    var list = p.certs || [];
    var certs = [], stds = [];
    var STD = /^(\d{2}\s?CFR|EN[\s-]|ISO[\s-]|AS\/?NZS|GB|JIS|TB\s?117|CPSIA|RoHS|REACH|GPSR|Prop\s?65|LFGB|FDA)/i;
    list.forEach(function (c) {
      var k = meta[c] || (STD.test(c) ? "standard" : "cert");
      if (k === "standard") stds.push(c); else certs.push(c);
    });
    return { certs: certs, stds: stds };
  }

  function certLine(p) {
    var sp = splitCerts(p);
    if (!sp.certs.length) return "暂未录入（对话里说「我们有 CE 证书」即可录入）";
    return sp.certs.join("、");
  }

  function stdLine(p) {
    var sp = splitCerts(p);
    if (!sp.stds.length) return "暂未登记";
    return sp.stds.join("、") + "（按标准要求自报，未附检测报告）";
  }

  function renderProfile() {
    var p = S.profile;
    var dl = $("profile");
    if (!p) return;
    var prod = p.product || {};
    var mk = p.market || {};
    var names = { eu: "欧盟", us: "美国", uk: "英国", jp: "日本",
                  asean: "东盟", me: "中东", af: "非洲" };
    var rows = [
      ["产品", prod.name_cn || "未填写"],
      ["品类", CAT_NAMES[prod.category] || "未判定"],
      ["材质", prod.material || "待确认"],
      ["是否带电", prod.powered === true ? "带电" : (prod.powered === false ? "不带电" : "待确认")],
      ["目标市场", names[mk.region] || "待确认"],
      ["已有认证", certLine(p)],
      ["已确认满足", stdLine(p)],
      ["规格", specLine(prod)]
    ];
    dl.innerHTML = rows.map(function (r) {
      var cls = (r[1] === "待确认" || r[1] === "未填写") ? ' class="pending"' : "";
      return "<dt>" + esc(r[0]) + "</dt><dd" + cls + ">" + esc(r[1]) + "</dd>";
    }).join("");
  }

  function renderTab() {
    var body = $("tabBody");
    var a = S.artifacts || {};
    if (S.tab === "listing") body.innerHTML = renderListing(a.listing, a.guard_warnings);
    else if (S.tab === "compliance") body.innerHTML = renderCompliance(a.compliance);
    else body.innerHTML = renderPolicy(a.policies);
  }

  function renderListing(l, warns) {
    if (!l) return '<p class="empty">上传产品照片，或直接描述产品，这里会生成英文 listing。</p>';
    var out = [];
    if (S.quoteOpen) {
      out.push(quoteForm());
    } else {
      out.push('<div class="expbar"><button class="mini primary" onclick="openQuote()">生成报价单</button>' +
        '<span class="why" style="margin-left:8px">先改公司名、单价、条款，再导出 PDF 或 Word</span></div>');
    }
    out.push('<div class="listing">');
    out.push("<h3>" + esc(l.title) + "</h3><ul>");
    (l.bullets || []).forEach(function (b) { out.push("<li>" + esc(b) + "</li>"); });
    out.push("</ul>");
    if (l.description) out.push('<p class="desc">' + esc(l.description) + "</p>");
    if (l.keywords && l.keywords.length) {
      out.push('<div class="kw">');
      l.keywords.forEach(function (k) { out.push("<span>" + esc(k) + "</span>"); });
      out.push("</div>");
    }
    if (l.price_band) {
      out.push('<div class="price"><b>' + esc(l.price_band) + "</b>");
      if (l.price_basis) out.push("<br>" + esc(l.price_basis));
      out.push("</div>");
    }
    if (l.claims_to_avoid && l.claims_to_avoid.length) {
      out.push('<div class="warn">不可声称：' + l.claims_to_avoid.map(esc).join("；") + "</div>");
    }
    if (warns && warns.length) {
      out.push('<div class="warn"><b>自动校验提示 ' + warns.length + ' 处</b>');
      warns.forEach(function (w) { out.push("<br>· " + esc(w)); });
      out.push("</div>");
    }
    out.push("</div>");
    return out.join("");
  }

  function renderCompliance(list) {
    if (!list || !list.length) return '<p class="empty">方案生成后，这里会列出这份产品真正要过的合规项。</p>';
    var map = { must: "必须先做", should: "建议做", info: "了解即可" };
    var out = ['<div class="expbar"><button class="mini primary" onclick="exportCompliance()">导出 PDF 清单</button>' +
      '<span class="why" style="margin-left:8px">带勾选框，可直接打印给检测机构或代理</span></div>'];
    out.push('<div class="items">');
    list.forEach(function (it) {
      out.push('<div class="item"><div class="row1">');
      if (it.have) {
        out.push('<span class="badge b-verified">已具备</span>');
      } else {
        out.push('<span class="badge b-' + esc(it.severity) + '">' + esc(map[it.severity] || it.severity) + "</span>");
      }
      out.push('<span class="name">' + esc(it.title) + "</span>");
      if (!it.have) {
        if (!it.confirmed) {
          out.push('<button class="badge b-unverified" title="打开原文核对后点这里" onclick="verifyItem(\'rule\',\'' + esc(it.rule_id) + '\',this)">待核对</button>');
        } else {
          out.push('<span class="badge b-verified">已核对</span>');
        }
        if (it.cert) {
          out.push('<button class="badge b-claim" title="贵司已持有这项资质？点一下写进企业档案" onclick="claimCert(\'' + esc(it.rule_id) + '\',this)">我已具备</button>');
        }
      }
      out.push("</div>");
      out.push("<p>" + esc(it.requirement) + "</p>");
      if (it.why) out.push('<p class="why">为什么适用：' + esc(it.why) + "</p>");
      if (it.source_status === "changed") {
        out.push('<span class="badge b-changed">来源有更新，需复核</span>');
      } else if (it.source_status === "dead") {
        out.push('<span class="badge b-changed">来源链接失效</span>');
      }
      if (it.have) {
        out.push(it.held_kind === "standard"
          ? '<p class="why">档案标记为满足「' + esc(it.held_by) + '」，建议补一份检测报告备查</p>'
          : '<p class="why">档案已登记「' + esc(it.held_by) + '」，仍需确认证书版本与有效期</p>');
      }
      if (it.source_url) out.push('<a href="' + esc(it.source_url) + '" target="_blank" rel="noopener">' + esc(it.source || "原文") + "</a>");
      out.push("</div>");
    });
    out.push("</div>");
    return out.join("");
  }

  function renderPolicy(list) {
    if (!list || !list.length) return '<p class="empty">在对话里问一句「我能申什么补贴」，这里会按你的档案筛出可申报项。</p>';
    var out = ['<div class="items">'];
    list.forEach(function (p) {
      out.push('<div class="item"><div class="row1"><span class="badge b-info">可申报</span>');
      out.push('<span class="name">' + esc(p.name) + "</span>");
      if (!p.confirmed) {
        out.push('<button class="badge b-unverified" title="打开原文核对后点这里" onclick="verifyItem(\'policy\',\'' + esc(p.id) + '\',this)">待确认</button>');
      } else {
        out.push('<span class="badge b-verified">已确认</span>');
        if (p.confirmed_by) {
          out.push('<span class="why" style="margin-left:6px">' + esc(p.confirmed_by) + " · " + esc((p.confirmed_at || "").slice(5)) + "</span>");
        }
      }
      out.push("</div><p>" + esc(p.condition) + "</p>");
      out.push('<p class="why">' + esc(p.support) + "</p>");
      out.push('<p class="why">截止：' + esc(p.deadline) + "　来源：" + esc(p.source) + "</p>");
      if (p.source_url) {
        var lbl = p.link_checked ? "查看原文" : "来源官网（首页）";
        out.push('<a href="' + esc(p.source_url) + '" target="_blank" rel="noopener">' + lbl + "</a>");
      } else {
        out.push('<span class="why">未提供可访问链接，请按机构名自行检索</span>');
      }
      if (p.note) out.push('<p class="why">注：' + esc(p.note) + "</p>");
      if (p.draft) {
        out.push('<div class="draft"><div class="draft-head">AI 起草的修订 <span class="muted">未生效</span></div>');
        if (p.draft.diff && p.draft.diff.length) {
          p.draft.diff.forEach(function (d) {
            out.push('<div class="dfield"><div class="dlab">' + esc(d.label) + "</div>");
            out.push('<div class="dold">' + esc(d.before || "（空）") + "</div>");
            out.push('<div class="dnew">' + esc(d.after || "（空）") + "</div></div>");
          });
        } else {
          out.push('<p class="why">与现有摘要无实质差异。</p>');
        }
        if (p.draft.change_note) out.push('<p class="why">说明：' + esc(p.draft.change_note) + "</p>");
        out.push('<div class="draft-actions">');
        out.push('<button class="mini primary" onclick="adoptDraft(\'' + esc(p.id) + '\',this)">采纳并标记已核对</button>');
        out.push('<button class="mini" onclick="discardDraft(\'' + esc(p.id) + '\',this)">放弃</button>');
        out.push("</div></div>");
      } else if (p.source_status === "changed") {
        out.push('<div class="draft-actions"><button class="mini" onclick="redraftItem(\'' + esc(p.id) + '\',this)">让 AI 起草修订</button></div>');
      }
      if (p.source_status === "changed") {
        out.push('<span class="badge b-changed">来源有更新，需复核</span>');
      }
      if (p.source_checked_at) {
        out.push('<p class="why" style="opacity:.7">来源检查于 ' + esc(p.source_checked_at) + "</p>");
      }
      if (p.confirmed && p.materials) {
        out.push('<div class="matbox"><div class="draft-head">申报材料清单 · 照着准备</div>');
        (p.materials.items || []).forEach(function (m, i) {
          out.push('<div class="matrow"><span class="matno">' + (i + 1) + "</span>" +
            esc(m.name) + '<span class="matmeta">' + esc(m.owner) + (m.days ? " · " + esc(m.days) : "") + "</span></div>");
          if (m.note) out.push('<div class="matnote">' + esc(m.note) + "</div>");
        });
        if (p.materials.first_step) out.push('<p class="why">第一步：' + esc(p.materials.first_step) + "</p>");
        if (p.materials.caution) out.push('<p class="why">注意：' + esc(p.materials.caution) + "</p>");
        out.push("</div>");
      } else if (p.confirmed) {
        out.push('<div class="draft-actions"><button class="mini" onclick="genMaterials(\'' + esc(p.id) + '\',this)">生成申报材料清单</button></div>');
      }
      out.push("</div>");
    });
    out.push("</div>");
    return out.join("");
  }

  window.verifyItem = function (kind, id, node) {
    if (!confirm("确认已打开来源、逐字核对过这一条？")) return;
    node.disabled = true;
    post("/api/verify", { session_id: S.sid, kind: kind, id: id }).then(function (d) {
      if (d.ok) {
        node.textContent = kind === "policy" ? "已确认" : "已核对";
        node.className = "badge b-verified";
        refreshArtifacts();          // 立刻重拉，材料清单按钮才会即时出现
      } else {
        node.disabled = false;
        alert("标记失败：" + (d.error || "未知错误"));
      }
    }).catch(function (e) {
      node.disabled = false;
      alert("请求失败：" + e.message);
    });
  };

  function refreshArtifacts() {
    if (!S.sid) return;
    get("/api/session?id=" + encodeURIComponent(S.sid)).then(function (d) {
      if (!d || !d.ok) return;
      S.artifacts = d.artifacts || {};
      if (d.profile) { S.profile = d.profile; renderProfile(); }
      if (d.state) $("stateTag").textContent = ({ new: "待建档", clarify: "待确认", done: "已出方案" })[d.state] || d.state;
      renderTab();
    });
  }

  window.redraftItem = function (id, node) {
    node.disabled = true;
    node.textContent = "起草中…";
    post("/api/redraft", { id: id }).then(function (d) {
      if (d.ok) { refreshArtifacts(); } else { node.disabled = false; node.textContent = "让 AI 起草修订"; alert(d.error || "起草失败"); }
    }).catch(function (e) { node.disabled = false; node.textContent = "让 AI 起草修订"; alert(e.message); });
  };

  function qf(label, id, val, ph) {
    return '<div class="qfield"><label>' + esc(label) + '</label><input id="' + id + '" value="' +
      esc(val || "") + '" placeholder="' + esc(ph || "") + '"></div>';
  }

  function quoteForm() {
    var p = S.profile || {}, prod = p.product || {}, sp = prod.specs || {};
    var L = (S.artifacts || {}).listing || {};
    var co = (p.name && p.name !== "未填写") ? p.name : "";
    return '<div class="matbox"><div class="draft-head">报价单参数　<span class="muted">留空就用档案里的</span></div>' +
      '<div class="qgrid">' +
      qf("公司名", "q_company", co, "留空则用档案里的公司名") +
      qf("买家名称", "q_to", "", "可留空，打印后手写") +
      qf("单价（FOB）", "q_price", L.price_band || "", "如 USD 320-420") +
      qf("MOQ", "q_moq", sp.moq || "", "如 50 pcs") +
      qf("交期", "q_lead", sp.lead_time || "", "如 30 days") +
      qf("有效期（天）", "q_valid", "30", "30") +
      '</div></div>' +
      '<div style="margin-top:8px">' + qf("付款方式", "q_payment",
        "30% T/T deposit, balance against copy of B/L", "") + "</div>" +
      '<div class="draft-actions">' +
      '<button class="mini primary" onclick="doQuote(\'pdf\')">生成 PDF</button>' +
      '<button class="mini" onclick="doQuote(\'docx\')">生成 Word</button>' +
      '<button class="mini" onclick="closeQuote()">收起</button></div></div>';
  }

  window.openQuote = function () { S.quoteOpen = true; renderTab(); };
  window.closeQuote = function () { S.quoteOpen = false; renderTab(); };
  window.doQuote = function (kind) {
    if (!S.sid) return;
    var keys = ["company", "to", "price", "moq", "lead", "valid", "payment"];
    var q = [];
    keys.forEach(function (k) {
      var el = $("q_" + k);
      var v = el ? el.value.trim() : "";
      if (v) q.push(k + "=" + encodeURIComponent(v));
    });
    var url = "/api/export/quote" + (kind === "docx" ? ".docx" : "") +
      "?sid=" + encodeURIComponent(S.sid) + (q.length ? "&" + q.join("&") : "");
    window.open(url, "_blank");
  };

  window.exportQuote = function () {
    if (!S.sid) return;
    window.open("/api/export/quote?sid=" + encodeURIComponent(S.sid), "_blank");
  };

  window.exportQuoteDocx = function () {
    if (!S.sid) return;
    window.open("/api/export/quote.docx?sid=" + encodeURIComponent(S.sid), "_blank");
  };

  window.exportCompliance = function () {
    if (!S.sid) return;
    window.open("/api/export/compliance?sid=" + encodeURIComponent(S.sid), "_blank");
  };

  window.claimCert = function (ruleId, node) {
    if (!confirm("确认贵司已持有这项资质？\n登记后会写入企业档案，并允许 listing 里出现该认证表述。")) return;
    node.disabled = true;
    node.textContent = "登记中…";
    post("/api/claim", { session_id: S.sid, rule_id: ruleId }).then(function (d) {
      if (d.ok) { refreshArtifacts(); }
      else { node.disabled = false; node.textContent = "我已具备"; alert(d.error || "登记失败"); }
    }).catch(function (e) {
      node.disabled = false; node.textContent = "我已具备"; alert(e.message);
    });
  };

  window.genMaterials = function (id, node) {
    node.disabled = true;
    node.textContent = "整理中…";
    post("/api/materials", { id: id }).then(function (d) {
      if (d.ok) { refreshArtifacts(); } else { node.disabled = false; node.textContent = "生成申报材料清单"; alert(d.error || "生成失败"); }
    }).catch(function (e) { node.disabled = false; node.textContent = "生成申报材料清单"; alert(e.message); });
  };

  window.adoptDraft = function (id, node) {
    if (!confirm("确认草稿与原文一致？采纳后将写入正式字段并标记为已核对。")) return;
    node.disabled = true;
    post("/api/adopt", { id: id }).then(function (d) {
      if (d.ok) { refreshArtifacts(); } else { node.disabled = false; alert(d.error || "采纳失败"); }
    });
  };

  window.discardDraft = function (id, node) {
    if (!confirm("放弃这次修订？原内容保持不变。")) return;
    node.disabled = true;
    post("/api/discard", { id: id }).then(function () { refreshArtifacts(); });
  };

  function loadByok() {
    get("/api/byok").then(function (d) {
      var hint = $("b_hint");
      if (!d || !d.ok) return;
      if (d.configured) {
        $("b_url").value = d.base_url || "";
        $("b_model").value = d.model || "";
        $("b_vision").value = d.vision_model || "";
        $("b_key").placeholder = "已配置：" + d.key + "（留空则不改）";
        hint.textContent = "当前已启用你自己的密钥，额度走你的账户。";
      } else {
        hint.textContent = "当前用的是部署方密钥或样例模式。";
      }
    }).catch(function () {});
  }

  function showSid() {
    if (!S.sid) return;
    var el = $("sidTag");
    el.style.display = "inline-block";
    el.textContent = "会话 " + S.sid.slice(0, 6);
    el.title = "本次咨询的独立档案号，关闭标签页后自动清空，不会留给下一位使用者";
  }

  function loadFresh() {
    get("/api/freshness").then(function (d) {
      if (!d || !d.at) return;
      var el = $("freshTag");
      var s = d.stats || {};
      el.style.display = "inline-block";
      el.textContent = "来源检查 " + d.at.slice(5);
      el.title = "共 " + (s.checked || 0) + " 条：" + (s.same || 0) + " 未变，" +
        (s.changed || 0) + " 疑似更新，" + (s.dead || 0) + " 不可达";
    }).catch(function () {});
  }

  function send(text) {
    if (S.busy) return;
    text = (text || "").trim();
    if (!text) return;
    S.busy = true;
    addMsg("user", text);
    setChips([]);
    var t = typing();
    post("/api/chat", { session_id: S.sid, text: text })
      .then(function (d) { t.remove(); apply(d, false); })
      .catch(function (e) { t.remove(); addMsg("bot", "请求失败：" + e.message + "。检查后端是否还在运行。"); })
      .then(function () { S.busy = false; $("text").value = ""; $("text").focus(); });
  }

  function upload(file) {
    if (!file || S.busy) return;
    if (file.size > 5 * 1024 * 1024) { addMsg("bot", "图片超过 5MB，压缩一下再传。"); return; }
    S.busy = true;
    var nm = file.name.length > 22 ? file.name.slice(0, 18) + "…" : file.name;
    addMsg("user", "[上传照片] " + nm);
    var t = typing();
    var fr = new FileReader();
    fr.onload = function () {
      post("/api/upload", { session_id: S.sid, data: String(fr.result), mime: file.type || "image/jpeg" })
        .then(function (d) { t.remove(); apply(d, false); })
        .catch(function (e) { t.remove(); addMsg("bot", "上传失败：" + e.message); })
        .then(function () { S.busy = false; });
    };
    fr.readAsDataURL(file);
  }

  document.addEventListener("DOMContentLoaded", function () {
    $("composer").addEventListener("submit", function (e) { e.preventDefault(); send($("text").value); });
    $("file").addEventListener("change", function (e) {
      if (e.target.files && e.target.files[0]) upload(e.target.files[0]);
      e.target.value = "";
    });
    $("byokBtn").addEventListener("click", function () {
      var p = $("byokPanel");
      p.style.display = p.style.display === "none" ? "block" : "none";
      if (p.style.display === "block") loadByok();
    });
    $("byokClose").addEventListener("click", function () { $("byokPanel").style.display = "none"; });
    $("b_save").addEventListener("click", function () {
      var body = {
        base_url: $("b_url").value.trim(),
        model: $("b_model").value.trim(),
        vision_model: $("b_vision").value.trim(),
        api_key: $("b_key").value.trim()
      };
      if (!body.base_url || !body.model) { alert("地址和模型名要填"); return; }
      if (!body.api_key) { alert("密钥要填（已配置过可点清除后重填）"); return; }
      post("/api/byok", body).then(function (d) {
        if (d.ok) {
          $("b_key").value = "";
          $("modeTag").textContent = d.mock ? "样例模式" : "已接入模型";
          $("modeTag").className = "tag " + (d.mock ? "tag-mock" : "tag-live");
          loadByok();
          addMsg("bot", "密钥已保存并启用，接下来走你自己的额度。");
        } else { alert(d.error || "保存失败"); }
      });
    });
    $("b_clear").addEventListener("click", function () {
      if (!confirm("清除已保存的密钥？")) return;
      post("/api/byok", { clear: true }).then(function () { loadByok(); alert("已清除"); });
    });

    $("refreshBtn").addEventListener("click", function () {
      refreshArtifacts();
      loadFresh();
    });
    $("resetBtn").addEventListener("click", function () {
      sessionStorage.removeItem("ccm_sid");
      post("/api/reset", {}).then(function (d) {
        S.sid = d.session_id; sessionStorage.setItem("ccm_sid", S.sid);
        showSid();
        $("msgs").innerHTML = ""; S.artifacts = {}; S.profile = null;
        renderTab(); apply(d, true);
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (x) {
      x.classList.toggle("active", x.getAttribute("data-tab") === S.tab);
    });
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (b) {
      b.addEventListener("click", function () {
        Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (x) { x.classList.remove("active"); });
        b.classList.add("active");
        S.tab = b.getAttribute("data-tab");
        renderTab();
      });
    });

    get("/api/health").then(function (d) {
      if (!d || !d.auth) return;
      var out = $("logoutBtn");
      out.style.display = "inline-block";
      out.addEventListener("click", function () {
        fetch("/api/logout").then(function () { location.replace("/login"); });
      });
    }).catch(function () {});

    loadFresh();
    setTimeout(loadFresh, 30000);

    var fromUrl = "";
    try { fromUrl = new URLSearchParams(location.search).get("sid") || ""; } catch (e) { fromUrl = ""; }
    // sessionStorage：同一标签页刷新保留，关掉或换标签页就是新客户
    var saved = fromUrl || sessionStorage.getItem("ccm_sid");
    if (!saved) {
      // 新访客：清空界面上可能残留的内容，避免看到别人的对话
      $("msgs").innerHTML = "";
      S.artifacts = {}; S.profile = null;
      renderTab();
    }
    var p = saved ? get("/api/session?id=" + encodeURIComponent(saved)) : post("/api/reset", {});
    p.then(function (d) {
      if (!d.ok) { greet(); return; }
      S.sid = d.session_id; sessionStorage.setItem("ccm_sid", S.sid);
      showSid();
      if (d.messages && d.messages.length) {
        d.messages.forEach(function (m) { addMsg(m.role === "user" ? "user" : "bot", m.text); });
        S.mock = !!d.mock; $("modeTag").textContent = S.mock ? "样例模式" : "已接入模型";
        $("modeTag").className = "tag " + (S.mock ? "tag-mock" : "tag-live");
        S.profile = d.profile; S.artifacts = d.artifacts || {};
        renderProfile(); renderTab();
        $("stateTag").textContent = ({ new: "待建档", clarify: "待确认", done: "已出方案" })[d.state] || d.state;
      } else { apply(d, true); }
    }).catch(function () {
      addMsg("bot", "连不上服务。先在本机运行 python run.py，再用浏览器打开提示的地址。");
    });
  });
})();
