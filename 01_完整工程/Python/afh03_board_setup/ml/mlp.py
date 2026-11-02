# -*- coding: utf-8 -*-
"""
mlp.py —— 纯 numpy 的多层感知机（训练 + 推理共用；板端只依赖 numpy）

为什么不用 torch/sklearn：开发板（RK3576J）只有 numpy，没有 torch/sklearn。
本模块把权重存成 .npz（float32），推理是一次矩阵乘 -> 板上 <0.1ms，无需任何框架。

特性：
  * 标准化（均值/方差随模型一起存）
  * 两层隐层 ReLU + softmax
  * Adam、mini-batch、L2、类别权重、早停
  * `decide()` 带**弃权阈值**：概率不够就不下结论（返回 -1），交给规则层兜底
"""
import numpy as np

ABSTAIN = -1

class MLP:
    def __init__(self, n_in, n_out, hidden=(64, 32), seed=0):
        rng = np.random.default_rng(seed)
        dims = [n_in] + list(hidden) + [n_out]
        self.W = []
        self.b = []
        for i in range(len(dims) - 1):

            self.W.append((rng.standard_normal((dims[i], dims[i + 1]))
                            * np.sqrt(2.0 / dims[i])).astype(np.float32))
            self.b.append(np.zeros(dims[i + 1], np.float32))
        self.mean = np.zeros(n_in, np.float32)
        self.std = np.ones(n_in, np.float32)
        self.meta = {}

    def fit_scaler(self, X):
        self.mean = X.mean(0).astype(np.float32)
        s = X.std(0)
        s[s < 1e-8] = 1.0
        self.std = s.astype(np.float32)
        return self

    def _x(self, X):
        return ((X - self.mean) / self.std).astype(np.float32)

    def forward(self, X, cache=False):
        h = self._x(X)
        acts = [h]
        for i in range(len(self.W) - 1):
            h = np.maximum(h @ self.W[i] + self.b[i], 0.0)
            acts.append(h)
        z = h @ self.W[-1] + self.b[-1]
        z -= z.max(1, keepdims=True)
        e = np.exp(z)
        p = e / e.sum(1, keepdims=True)
        if cache:
            return p, acts
        return p

    def predict_proba(self, X):
        return self.forward(np.asarray(X, np.float32))

    def predict(self, X):
        return self.predict_proba(X).argmax(1)

    def decide(self, X, abstain_thr=0.0):
        """返回 (labels, probs, conf)；概率低于阈值 -> ABSTAIN(-1)"""
        p = self.predict_proba(X)
        lab = p.argmax(1)
        conf = p.max(1)
        if abstain_thr > 0:
            lab = np.where(conf >= abstain_thr, lab, ABSTAIN)
        return lab, p, conf

    def fit(self, X, y, Xv=None, yv=None, epochs=300, lr=0.01, batch=128,
            l2=1e-4, class_weight=None, patience=25, verbose=True, seed=0):
        X = np.asarray(X, np.float32)
        y = np.asarray(y, np.int64)
        self.fit_scaler(X)
        n, K = len(X), len(self.b[-1])
        rng = np.random.default_rng(seed)
        params = self.W + self.b
        m = [np.zeros_like(p) for p in params]
        v = [np.zeros_like(p) for p in params]
        b1, b2, eps, t = 0.9, 0.999, 1e-8, 0
        w = np.ones(K, np.float32)
        if class_weight is not None:
            w = np.asarray(class_weight, np.float32)
        best = (1e9, None, 0)
        best_state = [p.copy() for p in params]
        for ep in range(1, epochs + 1):
            idx = rng.permutation(n)
            tot = 0.0
            for s in range(0, n, batch):
                bi = idx[s:s + batch]
                xb, yb = self._x(X[bi]), y[bi]

                h = xb
                acts = [h]
                for i in range(len(self.W) - 1):
                    h = np.maximum(h @ self.W[i] + self.b[i], 0.0)
                    acts.append(h)
                logits = h @ self.W[-1] + self.b[-1]
                logits -= logits.max(1, keepdims=True)
                e = np.exp(logits)
                p = e / e.sum(1, keepdims=True)
                yh = p[np.arange(len(yb)), yb]
                sw = w[yb]
                tot += float((-np.log(np.clip(yh, 1e-9, 1)) * sw).sum())

                g = p.copy()
                g[np.arange(len(yb)), yb] -= 1.0
                g *= sw[:, None] / len(yb)
                for i in range(len(self.W) - 1, -1, -1):
                    dW = acts[i].T @ g + l2 * self.W[i]
                    db = g.sum(0)
                    if i > 0:
                        g = (g @ self.W[i].T) * (acts[i] > 0)
                    t += 1
                    for prm, gr, mi, vi in ((self.W[i], dW, m[i], v[i]),
                                            (self.b[i], db, m[len(self.W) + i], v[len(self.W) + i])):
                        mi[:] = b1 * mi + (1 - b1) * gr
                        vi[:] = b2 * vi + (1 - b2) * gr * gr
                        mh = mi / (1 - b1 ** t)
                        vh = vi / (1 - b2 ** t)
                        prm -= lr * mh / (np.sqrt(vh) + eps)
            tr = tot / n
            if Xv is not None and yv is not None:
                pv = self.predict_proba(Xv)
                vl = float(-np.log(np.clip(pv[np.arange(len(yv)), yv], 1e-9, 1)).mean())
                if vl < best[0] - 1e-6:
                    best = (vl, ep, 0)
                    best_state = [p.copy() for p in self.W + self.b]
                else:
                    best = (best[0], best[1], best[2] + 1)
                if verbose and (ep % 20 == 0 or ep == 1):
                    av = float((self.predict(Xv) == yv).mean())
                    print("    ep%-4d train_loss %.4f  val_loss %.4f  val_acc %.3f"
                          % (ep, tr, vl, av))
                if best[2] >= patience:
                    if verbose:
                        print("    早停 @ep%d（best ep%d val_loss %.4f）" % (ep, best[1], best[0]))
                    break
            else:
                if verbose and ep % 20 == 0:
                    print("    ep%-4d train_loss %.4f" % (ep, tr))
        st = self.W + self.b
        for i, p in enumerate(best_state):
            st[i][...] = p
        return self

    def save(self, path):
        d = {"n_in": np.int32(self.W[0].shape[0]),
             "n_out": np.int32(self.b[-1].shape[0]),
             "hidden": np.array([w.shape[1] for w in self.W[:-1]], np.int32),
             "mean": self.mean, "std": self.std}
        for i, (W, b) in enumerate(zip(self.W, self.b)):
            d["W%d" % i] = W.astype(np.float32)
            d["b%d" % i] = b.astype(np.float32)
        for k, v in (self.meta or {}).items():
            if isinstance(v, (list, tuple)):
                d["meta_" + k] = np.array([str(x) for x in v])
            elif isinstance(v, str):
                d["meta_" + k] = np.array([v])
            else:
                d["meta_" + k] = np.array(v)
        np.savez_compressed(path, **d)

    @staticmethod
    def load(path):
        d = np.load(path, allow_pickle=False)
        n_in, n_out = int(d["n_in"]), int(d["n_out"])
        hidden = tuple(int(x) for x in d["hidden"]) if "hidden" in d else ()
        m = MLP(n_in, n_out, hidden or (64, 32))
        m.W, m.b = [], []
        i = 0
        while "W%d" % i in d:
            m.W.append(d["W%d" % i].astype(np.float32))
            m.b.append(d["b%d" % i].astype(np.float32))
            i += 1
        m.mean = d["mean"].astype(np.float32)
        m.std = d["std"].astype(np.float32)
        meta = {}
        for k in d.files:
            if k.startswith("meta_"):
                arr = d[k]
                meta[k[5:]] = arr.tolist() if arr.ndim else arr.item()
        m.meta = meta
        return m

def confusion(y_true, y_pred, K):
    cm = np.zeros((K, K), np.int64)
    for t, p in zip(y_true, y_pred):
        if 0 <= t < K and 0 <= p < K:
            cm[t, p] += 1
    return cm

def report(y_true, y_pred, names, title="", ignore=()):
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    K = len(names)
    m = np.array([i for i in range(K) if names[i] not in ignore])
    acc = float((y_true == y_pred).mean()) if len(y_true) else 0.0
    lines = ["%s  n=%d  acc=%.4f" % (title, len(y_true), acc)]
    cm = confusion(y_true, y_pred, K)
    lines.append("  类别            支持   P      R      F1")
    for i in range(K):
        tp = cm[i, i]
        sup = cm[i].sum()
        if sup == 0:
            continue
        prec = tp / max(1, cm[:, i].sum())
        rec = tp / max(1, sup)
        f1 = 2 * prec * rec / max(1e-9, prec + rec)
        lines.append("  %-14s %5d  %.3f  %.3f  %.3f"
                     % (names[i][:14], sup, prec, rec, f1))
    macro = np.mean([cm[i, i] / max(1, cm[i].sum()) for i in m]) if len(m) else 0.0
    lines.append("  宏平均召回 %.4f" % macro)

    pairs = []
    for i in range(K):
        for j in range(K):
            if i != j and cm[i, j] > 0:
                pairs.append((cm[i, j], names[i], names[j]))
    pairs.sort(reverse=True)
    if pairs:
        lines.append("  主要混淆：" + "；".join("%s->%s×%d" % (a, b, n) for n, a, b in pairs[:5]))
    return "\n".join(lines), cm
