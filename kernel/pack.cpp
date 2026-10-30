// aura-loading-prototype: 3D container loading kernel.
//   algo=ep    extreme points + randomized local search over loading order (first version)
//   algo=block block building on maximal spaces + greedy lookahead (kernel/blocks.hpp): wall / layer / corner
//              constructors and block ranking weights are parameters, so each strategy is a rule in aura/
// Input: line-based problem file (see docs/FORMAT.md). Output: result JSON + "@@m" metric line on stdout.
// Coordinates (mm): x = length (0 = front wall, L = door), y = width, z = height.
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <map>
#include <random>
#include <sstream>
#include <string>
#include <vector>

struct CType { std::string name; double L, W, H, max_kg, cost; int limit; };
struct Item {
  std::string id, sku, hazmat; double l, w, h, kg, max_top; int rot; bool fragile; int stop;
  // rot: 0 = any of 6 orientations, 1 = upright only (h stays vertical), 2 = fixed as given
};
struct Placed { int item; double x, y, z, dx, dy, dz; double load = 0; int seq; };
struct Bin { int ctype; std::vector<Placed> p; double kg = 0, vol = 0; std::vector<std::array<double,3>> eps;
  std::map<std::string, size_t> fail; bool eps_sorted = false;  // sku+dims -> bin size at last failure (bin unchanged => still fails)
};

struct Params {
  // merit weights (lower merit = better position)
  double w_x = 1.0, w_z = 0.15, w_y = 0.02, w_center = 0.0;
  // sort: 0 volume desc, 1 base-area desc, 2 weight desc, 3 height desc, 4 input order
  int sort = 0; bool sort_stop = true;
  double min_support = 0.75; bool lifo = true; double hazmat_sep = 0; bool rotate = true;
  // container choice: 0 = best volume/cost per bin, 1 = fixed first type only
  int cpolicy = 0; int iters = 200; double time_ms = 3000; unsigned seed = 1;
  double cog_x_lo = 0.0, cog_x_hi = 1.0, cog_y_lo = 0.0, cog_y_hi = 1.0;
};

static std::vector<CType> CT; static std::vector<Item> IT; static Params P;
struct Sol;

static bool overlap1(double a0, double a1, double b0, double b1) { return a0 < b1 - 1e-6 && b0 < a1 - 1e-6; }

static void orientations(const Item& it, std::vector<std::array<double,3>>& out) {
  out.clear();
  if (it.rot == 2 || !P.rotate) { out.push_back({it.l, it.w, it.h}); return; }
  out.push_back({it.l, it.w, it.h}); out.push_back({it.w, it.l, it.h});
  if (it.rot == 0) {
    out.push_back({it.l, it.h, it.w}); out.push_back({it.h, it.l, it.w});
    out.push_back({it.w, it.h, it.l}); out.push_back({it.h, it.w, it.l});
  }
}

// try to place item at (x,y,z) with dims d; returns merit or +inf
static double evaluate(const Bin& b, int ii, double x, double y, double z, const std::array<double,3>& d,
                       std::vector<std::pair<int,double>>* sup, double cutoff = INFINITY) {
  const CType& c = CT[b.ctype]; const Item& it = IT[ii];
  if (x + d[0] > c.L + 1e-6 || y + d[1] > c.W + 1e-6 || z + d[2] > c.H + 1e-6) return INFINITY;
  if (b.kg + it.kg > c.max_kg + 1e-6) return INFINITY;
  // merit depends only on the position, so compute it first and skip the O(n) checks when it cannot win
  double m = P.w_x * (x + d[0]) / c.L + P.w_z * (z + d[2]) / c.H + P.w_y * y / c.W;
  if (P.w_center > 0) m += P.w_center * std::fabs(y + d[1] / 2 - c.W / 2) / c.W * (it.kg / 50.0);
  if (m >= cutoff) return INFINITY;
  double area = d[0] * d[1], supported = 0; std::vector<std::pair<int,double>> s;
  for (size_t k = 0; k < b.p.size(); ++k) {
    const Placed& q = b.p[k];
    bool ox = overlap1(x, x + d[0], q.x, q.x + q.dx), oy = overlap1(y, y + d[1], q.y, q.y + q.dy);
    if (ox && oy && overlap1(z, z + d[2], q.z, q.z + q.dz)) return INFINITY;
    if (z > 0 && ox && oy && std::fabs(q.z + q.dz - z) < 1e-3) {
      double a = (std::min(x + d[0], q.x + q.dx) - std::max(x, q.x)) * (std::min(y + d[1], q.y + q.dy) - std::max(y, q.y));
      supported += a; s.push_back({(int)k, a});
    }
    if (P.lifo && IT[q.item].stop > it.stop && q.x >= x + d[0] - 1e-6 && oy && overlap1(z, z + d[2], q.z, q.z + q.dz))
      return INFINITY;  // a later-unloaded box would sit between this box and the door
    if (P.lifo && IT[q.item].stop < it.stop && q.x + q.dx <= x + 1e-6 && oy && overlap1(z, z + d[2], q.z, q.z + q.dz))
      return INFINITY;  // this (later-unloaded) box would block an earlier-unloaded one
    if (P.hazmat_sep > 0 && !it.hazmat.empty() && !IT[q.item].hazmat.empty() && IT[q.item].hazmat != it.hazmat) {
      double gx = std::max(q.x - (x + d[0]), x - (q.x + q.dx));
      if (gx < P.hazmat_sep) return INFINITY;
    }
  }
  if (z > 0) {
    if (supported < P.min_support * area - 1e-6) return INFINITY;
    for (auto& [k, a] : s) {
      const Placed& q = b.p[k];
      if (q.load + it.kg * a / supported > IT[q.item].max_top + 1e-6) return INFINITY;
    }
  }
  if (sup) *sup = s;
  return m;
}

static bool place(Bin& b, int ii, int seq) {
  const Item& ti = IT[ii];
  std::string fk = ti.sku + "|" + std::to_string(ti.l) + "|" + std::to_string(ti.w) + "|" + std::to_string(ti.h) + "|" + std::to_string(ti.kg) + "|" + std::to_string(ti.stop);
  auto fi = b.fail.find(fk);
  if (fi != b.fail.end() && fi->second == b.p.size()) return false;
  std::vector<std::array<double,3>> ors; orientations(IT[ii], ors);
  double best = INFINITY; size_t be = 0; std::array<double,3> bd{};
  if (!b.eps_sorted) {  // deepest / lowest points first so the merit cutoff prunes early
    std::sort(b.eps.begin(), b.eps.end(), [](auto& a, auto& c) { return a[0] != c[0] ? a[0] < c[0] : a[2] != c[2] ? a[2] < c[2] : a[1] < c[1]; });
    b.eps_sorted = true;
  }
  for (size_t e = 0; e < b.eps.size(); ++e)
    for (auto& d : ors) {
      double m = evaluate(b, ii, b.eps[e][0], b.eps[e][1], b.eps[e][2], d, nullptr, best);
      if (m < best) { best = m; be = e; bd = d; }
    }
  if (!std::isfinite(best)) { b.fail[fk] = b.p.size(); return false; }
  auto pt = b.eps[be]; std::vector<std::pair<int,double>> sup;
  evaluate(b, ii, pt[0], pt[1], pt[2], bd, &sup);
  double tot = 0; for (auto& s : sup) tot += s.second;
  for (auto& [k, a] : sup) b.p[k].load += IT[ii].kg * a / tot;
  b.p.push_back({ii, pt[0], pt[1], pt[2], bd[0], bd[1], bd[2], 0, seq});
  b.kg += IT[ii].kg; b.vol += bd[0] * bd[1] * bd[2];
  b.eps.erase(b.eps.begin() + be);
  const Placed& q = b.p.back();
  auto proj_z = [&](double x, double y, double z) {  // drop a point onto the highest top below it
    double best_z = 0;
    for (auto& r : b.p) if (x >= r.x - 1e-6 && x < r.x + r.dx - 1e-6 && y >= r.y - 1e-6 && y < r.y + r.dy - 1e-6 && r.z + r.dz <= z + 1e-6)
      best_z = std::max(best_z, r.z + r.dz);
    return best_z;
  };
  std::array<double,3> np[5] = {{q.x + q.dx, q.y, q.z}, {q.x, q.y + q.dy, q.z}, {q.x, q.y, q.z + q.dz},
                                {q.x + q.dx, q.y, 0}, {q.x, q.y + q.dy, 0}};
  np[3][2] = proj_z(np[3][0], np[3][1], q.z); np[4][2] = proj_z(np[4][0], np[4][1], q.z);
  const CType& c = CT[b.ctype];
  for (auto& p : np) {
    if (p[0] >= c.L - 1e-6 || p[1] >= c.W - 1e-6 || p[2] >= c.H - 1e-6) continue;
    bool inside = false;
    for (auto& r : b.p) if (p[0] >= r.x - 1e-6 && p[0] < r.x + r.dx - 1e-6 && p[1] >= r.y - 1e-6 && p[1] < r.y + r.dy - 1e-6 && p[2] >= r.z - 1e-6 && p[2] < r.z + r.dz - 1e-6) { inside = true; break; }
    if (inside) continue;
    bool dup = false; for (auto& e : b.eps) if (std::fabs(e[0]-p[0])<1e-3 && std::fabs(e[1]-p[1])<1e-3 && std::fabs(e[2]-p[2])<1e-3) { dup = true; break; }
    if (!dup) { b.eps.push_back(p); b.eps_sorted = false; }
  }
  // drop extreme points now covered by the new box
  b.eps.erase(std::remove_if(b.eps.begin(), b.eps.end(), [&](auto& p) {
    return p[0] >= q.x - 1e-6 && p[0] < q.x + q.dx - 1e-6 && p[1] >= q.y - 1e-6 && p[1] < q.y + q.dy - 1e-6 && p[2] >= q.z - 1e-6 && p[2] < q.z + q.dz - 1e-6; }), b.eps.end());
  return true;
}

struct Sol { std::vector<Bin> bins; std::vector<int> unplaced; double cost = 0; double score = 0; };

#include "blocks.hpp"

static Bin fill(int ct, const std::vector<int>& order, std::vector<char>& used, int& seq) {
  Bin b; b.ctype = ct; b.eps.push_back({0, 0, 0});
  for (int ii : order) if (!used[ii] && place(b, ii, seq)) { used[ii] = 1; ++seq; }
  return b;
}

static Sol build(const std::vector<int>& order) {
  Sol s; std::vector<char> used(IT.size(), 0); int seq = 0; std::vector<int> cnt(CT.size(), 0);
  size_t left = IT.size();
  while (left > 0) {
    int bestc = -1; Bin bestb; double bestv = -1; std::vector<char> bestu;
    for (size_t c = 0; c < CT.size(); ++c) {
      if (P.cpolicy == 1 && c != 0) break;
      if (CT[c].limit >= 0 && cnt[c] >= CT[c].limit) continue;
      std::vector<char> u = used; int sq = seq; Bin b = fill((int)c, order, u, sq);
      if (b.p.empty()) continue;
      size_t rem = 0; for (size_t i = 0; i < u.size(); ++i) rem += !u[i];
      // all remaining fits: prefer the cheapest such bin; otherwise best packed-volume per cost
      double v = (rem == 0 ? 1e12 - CT[c].cost : b.vol / CT[c].cost);
      if (v > bestv) { bestv = v; bestc = (int)c; bestb = std::move(b); bestu = std::move(u); }
    }
    if (bestc < 0) break;
    used = bestu; seq += (int)bestb.p.size(); cnt[bestc]++;
    left = 0; for (char u : used) left += !u;
    s.cost += CT[bestc].cost; s.bins.push_back(std::move(bestb));
  }
  for (size_t i = 0; i < IT.size(); ++i) if (!used[i]) s.unplaced.push_back((int)i);
  // objective: unplaced dominate, then cost, then how empty the last bin is (prefer consolidation)
  double last_fill = s.bins.empty() ? 0 : s.bins.back().vol / (CT[s.bins.back().ctype].L * CT[s.bins.back().ctype].W * CT[s.bins.back().ctype].H);
  s.score = s.unplaced.size() * 1e9 + s.cost * 1e3 + last_fill;
  return s;
}

static std::vector<int> initial_order() {
  std::vector<int> o(IT.size()); for (size_t i = 0; i < o.size(); ++i) o[i] = (int)i;
  auto key = [&](int i) {
    const Item& t = IT[i];
    switch (P.sort) { case 0: return t.l * t.w * t.h; case 1: return t.l * t.w; case 2: return t.kg; case 3: return t.h; default: return -(double)i; }
  };
  std::stable_sort(o.begin(), o.end(), [&](int a, int b) {
    if (P.sort_stop && IT[a].stop != IT[b].stop) return IT[a].stop > IT[b].stop;  // last stop loaded first
    if ((IT[a].max_top <= 0) != (IT[b].max_top <= 0)) return IT[b].max_top <= 0;  // fragile last
    return key(a) > key(b);
  });
  return o;
}

static std::string jesc(const std::string& s) { std::string r; for (char c : s) { if (c == '"' || c == '\\') r += '\\'; r += c; } return r; }

int main(int argc, char** argv) {
  std::string in, out; std::map<std::string, std::string> kv;
  for (int i = 1; i < argc; ++i) {
    std::string a = argv[i];
    if (a == "--in" && i + 1 < argc) in = argv[++i];
    else if (a == "--out" && i + 1 < argc) out = argv[++i];
    else if (a.find('=') != std::string::npos) kv[a.substr(0, a.find('='))] = a.substr(a.find('=') + 1);
  }
  if (in.empty()) { std::fprintf(stderr, "usage: pack --in problem.txt [--out result.json] [key=value ...]\n"); return 2; }
  std::ifstream f(in); std::string line;
  while (std::getline(f, line)) {
    if (line.empty() || line[0] == '#') continue;
    std::istringstream ss(line); std::string tag; ss >> tag;
    if (tag == "C") { CType c; ss >> c.name >> c.L >> c.W >> c.H >> c.max_kg >> c.cost >> c.limit; CT.push_back(c); }
    else if (tag == "I") {
      Item t; int qty; std::string hz, fr; ss >> t.id >> t.sku >> t.l >> t.w >> t.h >> t.kg >> qty >> t.rot >> t.max_top >> fr >> t.stop >> hz;
      t.fragile = fr == "1"; t.hazmat = hz == "-" ? "" : hz; if (t.fragile) t.max_top = 0;
      for (int q = 0; q < qty; ++q) { Item u = t; u.id = t.id + "#" + std::to_string(q + 1); IT.push_back(u); }
    } else if (tag == "R") { std::string k, v; ss >> k >> v; if (!kv.count(k)) kv[k] = v; }
  }
  auto D = [&](const char* k, double& v) { if (kv.count(k)) v = std::atof(kv[k].c_str()); };
  auto I = [&](const char* k, int& v) { if (kv.count(k)) v = std::atoi(kv[k].c_str()); };
  auto B = [&](const char* k, bool& v) { if (kv.count(k)) v = kv[k] == "1" || kv[k] == "true"; };
  D("w_x", P.w_x); D("w_z", P.w_z); D("w_y", P.w_y); D("w_center", P.w_center); I("sort", P.sort); B("sort_stop", P.sort_stop);
  D("min_support", P.min_support); B("lifo", P.lifo); D("hazmat_sep", P.hazmat_sep); B("rotate", P.rotate);
  I("cpolicy", P.cpolicy); I("iters", P.iters); D("time_ms", P.time_ms);
  if (kv.count("seed")) P.seed = (unsigned)std::atoi(kv["seed"].c_str());
  D("cog_x_lo", P.cog_x_lo); D("cog_x_hi", P.cog_x_hi); D("cog_y_lo", P.cog_y_lo); D("cog_y_hi", P.cog_y_hi);
  if (kv.count("only")) {  // restrict to one container type (used by the baseline)
    std::vector<CType> k; for (auto& c : CT) if (c.name == kv["only"]) k.push_back(c); CT = k;
  }
  if (CT.empty() || IT.empty()) { std::fprintf(stderr, "empty problem\n"); return 2; }

  auto t0 = std::chrono::steady_clock::now();
  auto elapsed = [&] { return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count(); };
  std::string algo = kv.count("algo") ? kv["algo"] : "ep";
  I("space", BP.space); D("w_vol", BP.w_vol); D("w_fill", BP.w_fill); D("w_yz", BP.w_yz); D("w_xy", BP.w_xy); D("w_big", BP.w_big);
  D("w_heavy", BP.w_heavy); D("w_waste", BP.w_waste); D("w_same", BP.w_same); I("depth", BP.depth); I("width", BP.width); I("maxw", BP.maxw);
  D("squeeze", BP.squeeze); B("anyrot", BP.anyrot); I("maxbins", BP.maxbins); D("noise", BP.noise); I("rwidth", BP.rwidth);
  if (algo != "block" && (BP.squeeze > 0 || BP.anyrot)) { std::fprintf(stderr, "squeeze/anyrot need algo=block\n"); return 2; }
  Sol best; int it = 0, improved = 0;
  if (algo == "block") { best = block_solve(P.time_ms, elapsed, &it); }
  std::vector<int> order = initial_order(); if (algo != "block") best = build(order); std::vector<int> bo = order;
  std::mt19937 rng(P.seed);
  for (; algo != "block" && it < P.iters && elapsed() < P.time_ms; ++it) {  // local search over loading order
    std::vector<int> o = bo; int n = (int)o.size(); int moves = 1 + rng() % 3;
    for (int m = 0; m < moves; ++m) {
      int a = rng() % n, len = 1 + rng() % std::max(1, n / 10), b = rng() % n;
      if (rng() % 2) { std::swap(o[a], o[b]); }
      else { len = std::min(len, n - a); std::vector<int> blk(o.begin() + a, o.begin() + a + len); o.erase(o.begin() + a, o.begin() + a + len);
             int pos = rng() % (o.size() + 1); o.insert(o.begin() + pos, blk.begin(), blk.end()); }
    }
    if (P.sort_stop) std::stable_sort(o.begin(), o.end(), [&](int x, int y) { return IT[x].stop > IT[y].stop; });
    Sol s = build(o);
    if (s.score < best.score - 1e-9) { best = std::move(s); bo = o; ++improved; }
  }

  // centre of gravity: slide the whole load along x/y inside the free space toward the centre
  // (relative positions, support and loading order are unchanged; the gap is filled with dunnage/bracing)
  bool cog_shift = true; B("cog_shift", cog_shift);
  if (cog_shift) for (auto& b : best.bins) {
    const CType& c = CT[b.ctype]; if (b.kg <= 0) continue;
    double mx = 0, my = 0, x0 = 1e18, x1 = 0, y0 = 1e18, y1 = 0;
    for (auto& q : b.p) { double k = IT[q.item].kg; mx += k * (q.x + q.dx / 2); my += k * (q.y + q.dy / 2);
      x0 = std::min(x0, q.x); x1 = std::max(x1, q.x + q.dx); y0 = std::min(y0, q.y); y1 = std::max(y1, q.y + q.dy); }
    double sx = std::clamp(c.L / 2 - mx / b.kg, -x0, c.L - x1), sy = std::clamp(c.W / 2 - my / b.kg, -y0, c.W - y1);
    for (auto& q : b.p) { q.x += sx; q.y += sy; }
  }
  // metrics
  double tv = 0, tc = 0, tkg = 0, tcap = 0, pv = 0, cog_viol = 0, worst_cx = 0.5, worst_cy = 0.5;
  std::ostringstream js; js.precision(6); js << std::fixed;
  js << "{\"containers\":[";
  for (size_t bi = 0; bi < best.bins.size(); ++bi) {
    const Bin& b = best.bins[bi]; const CType& c = CT[b.ctype];
    double cv = c.L * c.W * c.H, mx = 0, my = 0, mz = 0;
    for (auto& q : b.p) { double k = IT[q.item].kg; mx += k * (q.x + q.dx / 2); my += k * (q.y + q.dy / 2); mz += k * (q.z + q.dz / 2); }
    double cx = b.kg > 0 ? mx / b.kg / c.L : 0.5, cy = b.kg > 0 ? my / b.kg / c.W : 0.5, cz = b.kg > 0 ? mz / b.kg / c.H : 0;
    bool ok = cx >= P.cog_x_lo && cx <= P.cog_x_hi && cy >= P.cog_y_lo && cy <= P.cog_y_hi; cog_viol += !ok;
    if (std::fabs(cx - 0.5) > std::fabs(worst_cx - 0.5)) worst_cx = cx;
    if (std::fabs(cy - 0.5) > std::fabs(worst_cy - 0.5)) worst_cy = cy;
    // two-support beam model: front wall end (x=0) and door end (x=L)
    double rear = b.kg * cx, front = b.kg - rear;
    tv += b.vol; tc += cv; tkg += b.kg; tcap += c.max_kg;
    js << (bi ? "," : "") << "{\"type\":\"" << jesc(c.name) << "\",\"L\":" << c.L << ",\"W\":" << c.W << ",\"H\":" << c.H
       << ",\"max_kg\":" << c.max_kg << ",\"cost\":" << c.cost << ",\"kg\":" << b.kg << ",\"vol_util\":" << b.vol / cv
       << ",\"wt_util\":" << b.kg / c.max_kg << ",\"cog\":[" << cx << "," << cy << "," << cz << "],\"cog_ok\":" << (ok ? "true" : "false")
       << ",\"end_load_kg\":{\"front\":" << front << ",\"door\":" << rear << "},\"boxes\":[";
    for (size_t k = 0; k < b.p.size(); ++k) {
      const Placed& q = b.p[k]; const Item& t = IT[q.item];
      js << (k ? "," : "") << "{\"id\":\"" << jesc(t.id) << "\",\"sku\":\"" << jesc(t.sku) << "\",\"x\":" << q.x << ",\"y\":" << q.y << ",\"z\":" << q.z
         << ",\"dx\":" << q.dx << ",\"dy\":" << q.dy << ",\"dz\":" << q.dz << ",\"kg\":" << t.kg << ",\"stop\":" << t.stop
         << ",\"fragile\":" << (t.fragile ? "true" : "false") << ",\"hazmat\":\"" << jesc(t.hazmat) << "\",\"seq\":" << q.seq << "}";
    }
    js << "]}";
  }
  for (auto& t : IT) pv += t.l * t.w * t.h;
  // simple lower bound on containers of the largest type (volume and weight)
  double maxv = 0, maxkg = 0; for (auto& c : CT) { maxv = std::max(maxv, c.L * c.W * c.H); maxkg = std::max(maxkg, c.max_kg); }
  double totkg = 0; for (auto& t : IT) totkg += t.kg;
  int lb = (int)std::ceil(std::max(pv / maxv, totkg / maxkg) - 1e-9);
  std::map<std::string, int> mix; for (auto& b : best.bins) mix[CT[b.ctype].name]++;
  std::string mixs; for (auto& [k, v] : mix) mixs += (mixs.empty() ? "" : "+") + std::to_string(v) + "x" + k;
  js << "],\"unplaced\":[";
  for (size_t k = 0; k < best.unplaced.size(); ++k) js << (k ? "," : "") << "\"" << jesc(IT[best.unplaced[k]].id) << "\"";
  js << "],\"metrics\":{\"boxes\":" << IT.size() << ",\"containers\":" << best.bins.size() << ",\"mix\":\"" << mixs << "\",\"cost\":" << best.cost
     << ",\"vol_util\":" << (tc > 0 ? tv / tc : 0) << ",\"wt_util\":" << (tcap > 0 ? tkg / tcap : 0) << ",\"unplaced\":" << best.unplaced.size()
     << ",\"cog_violations\":" << cog_viol << ",\"worst_cog_x\":" << worst_cx << ",\"worst_cog_y\":" << worst_cy << ",\"lower_bound\":" << lb
     << ",\"iters\":" << it << ",\"improved\":" << improved << ",\"algo\":\"" << algo << "\",\"squeeze\":" << BP.squeeze
     << ",\"anyrot\":" << (BP.anyrot ? "true" : "false") << ",\"ms\":" << elapsed() << "}}\n";
  if (!out.empty()) { std::ofstream o(out); o << js.str(); }
  std::printf("@@m containers=%zu mix=%s cost=%.2f vol_util=%.4f wt_util=%.4f unplaced=%zu cog_violations=%.0f worst_cog_x=%.4f worst_cog_y=%.4f lower_bound=%d iters=%d algo=%s squeeze=%g anyrot=%d ms=%.0f\n",
              best.bins.size(), mixs.c_str(), best.cost, tc > 0 ? tv / tc : 0, tcap > 0 ? tkg / tcap : 0, best.unplaced.size(), cog_viol, worst_cx, worst_cy, lb, it, algo.c_str(), BP.squeeze, (int)BP.anyrot, elapsed());
  return best.unplaced.empty() ? 0 : 3;
}
