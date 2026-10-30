// Block-building engine (wall / layer / block / human-heuristic constructors share it; they differ in
// space selection and block ranking).  Included by pack.cpp after the globals CT / IT / P.
//
// State: maximal free spaces (cuboids) + placed blocks.  A block is nx*ny*nz boxes of one "box type"
// (same dims and constraints) in one orientation.  Each step picks a free space by the space rule, builds
// candidate blocks for it (counts per axis: max, and the count whose leftover is best filled by other box
// sizes = 1-D knapsack), ranks them by a weighted score, places the best feasible one at the space corner
// and splits every overlapped space into maximal sub-spaces.  Search = greedy lookahead with iterative
// widening: each of the top-w candidates is completed greedily and the best completion wins (Fanslau &
// Bortfeldt style), every completion is also a full solution and the best one is kept.
#pragma once
#include <functional>
#include <numeric>
#include <set>

struct BParams {
  int space = 0;          // 0 wall: min x, z, y   1 layer: min z, x, y   2 corner distance (Parreño)
  double w_vol = 1.0;     // block volume / largest candidate volume
  double w_fill = 0.0;    // block volume / space volume
  double w_yz = 0.0;      // cross-section coverage (walls)
  double w_xy = 0.0;      // footprint coverage (layers)
  double w_big = 0.0;     // big boxes first
  double w_heavy = 0.0;   // dense boxes low
  double w_waste = 0.0;   // knapsack leftover in y/z after the block (lower = better)
  double w_same = 0.0;    // same type as the block it stands on / next to (same-spec walls)
  int depth = 0;          // wall depth (x count) choice: 0 knapsack+max, 1 single slice only, 2 max only
  int width = 0;          // 0 iterative widening, otherwise fixed lookahead width
  int maxw = 1 << 20;     // widening cap (default: widen until the time budget runs out)
  double squeeze = 0;     // soft-carton compression tolerance (fraction of each dim), flagged in output
  bool anyrot = false;    // treat upright-only items as free orientation (assumption, flagged)
  double noise = 0.15;    // score noise of the randomized restarts after widening saturates (GRASP-style)
  int rwidth = 4;         // lookahead width of the randomized restarts
  int maxbins = 0;        // >0: stop after this many containers (rest reported unplaced; for single-container tests)
  int mixed = 0;          // mixed-spec column blocks: type A stacked under type B with the same footprint (fills the height)
};
static BParams BP;

struct BType { double d[3]; int rot; double max_top; bool fragile; int stop; std::string hazmat;
  std::vector<int> items; std::vector<double> pre; std::vector<std::array<double,3>> ors; double vol, dens; };
static std::vector<BType> BT;

struct Space { double x0, y0, z0, x1, y1, z1; };
struct PBlock { int t, o, nx, ny, nz, first; double x, y, z, bx, by, bz, kg, load; };
struct BState {
  int ct = 0; std::vector<Space> sp; std::vector<PBlock> bl; std::vector<int> used; double vol = 0, kg = 0; int phase_stop = 1 << 30;
};
struct Cand { int t, o, nx, ny, nz; double score, vol; int t2 = -1, o2 = 0, nz2 = 0; };  // t2 >= 0: mixed column, t2 stacked on t

static bool ovl(double a0, double a1, double b0, double b1) { return a0 < b1 - 1e-6 && b0 < a1 - 1e-6; }

static void build_types(const std::vector<int>& items) {
  BT.clear(); std::map<std::string, int> key;
  for (int i : items) {
    const Item& t = IT[i]; int rot = t.rot; if (BP.anyrot && rot == 1) rot = 0; if (!P.rotate) rot = 2;
    std::ostringstream k; k << t.l << '|' << t.w << '|' << t.h << '|' << rot << '|' << t.max_top << '|' << t.fragile << '|' << t.stop << '|' << t.hazmat;
    auto it = key.find(k.str()); int ti;
    if (it == key.end()) {
      ti = (int)BT.size(); key[k.str()] = ti; BType b; double s = 1 - BP.squeeze;
      b.d[0] = t.l * s; b.d[1] = t.w * s; b.d[2] = t.h * s; b.rot = rot; b.max_top = t.max_top; b.fragile = t.fragile; b.stop = t.stop; b.hazmat = t.hazmat;
      std::set<std::array<double,3>> os; double l = b.d[0], w = b.d[1], h = b.d[2];
      if (rot == 2) os.insert({l, w, h});
      else { os.insert({l, w, h}); os.insert({w, l, h});
        if (rot == 0) { os.insert({l, h, w}); os.insert({h, l, w}); os.insert({w, h, l}); os.insert({h, w, l}); } }
      b.ors.assign(os.begin(), os.end()); b.vol = l * w * h; BT.push_back(b);
    } else ti = it->second;
    BT[ti].items.push_back(i);
  }
  for (auto& b : BT) {
    std::stable_sort(b.items.begin(), b.items.end(), [](int a, int c) { return IT[a].kg > IT[c].kg; });
    b.pre.assign(b.items.size() + 1, 0); for (size_t k = 0; k < b.items.size(); ++k) b.pre[k + 1] = b.pre[k] + IT[b.items[k]].kg;
    b.dens = b.items.empty() ? 0 : b.pre.back() / b.items.size() / b.vol;
  }
}

// 1-D unbounded knapsack over the box sizes still available along an axis: best[r] = largest fill <= r (10 mm grid)
struct Knap { std::vector<int> best; int axis = -1; std::vector<char> avail_sig; };
static void knap_build(Knap& k, int axis, double len, const std::vector<int>& rem) {
  int n = (int)(len / 10) + 1; k.best.assign(n, 0); k.axis = axis; std::vector<int> sizes;
  for (size_t t = 0; t < BT.size(); ++t) if (rem[t] > 0) for (auto& o : BT[t].ors) {
    int s = (int)std::ceil(o[axis] / 10 - 1e-9); if (s > 0) sizes.push_back(s); }
  std::sort(sizes.begin(), sizes.end()); sizes.erase(std::unique(sizes.begin(), sizes.end()), sizes.end());
  for (int r = 1; r < n; ++r) { int b = k.best[r - 1]; for (int s : sizes) { if (s > r) break; b = std::max(b, k.best[r - s] + s); } k.best[r] = b; }
}
static double knap_fill(const Knap& k, double r) { int i = (int)(r / 10 + 1e-9); if (i < 0) return 0; if (i >= (int)k.best.size()) i = (int)k.best.size() - 1; return k.best[i] * 10.0; }

struct Engine {
  const CType* c; int ct; double cap; std::vector<int> total;  // per type count available to this bin
  double minbox[3]{};  // smallest box extent per axis among remaining (for space pruning)
  Knap ky, kz; bool multistop = false, anyhaz = false, anyload = false;
  mutable std::mt19937 rng{1}; mutable double noise = 0;

  void init(int ctype, const std::vector<int>& avail) {
    ct = ctype; c = &CT[ct]; cap = c->L * c->W * c->H; total = avail;
    std::set<int> stops; for (size_t t = 0; t < BT.size(); ++t) if (avail[t] > 0) { stops.insert(BT[t].stop); if (!BT[t].hazmat.empty()) anyhaz = true; if (BT[t].max_top < 1e8) anyload = true; }
    multistop = stops.size() > 1;
    knap_build(ky, 1, c->W, avail); knap_build(kz, 2, c->H, avail);
  }
  int rem(const BState& s, int t) const { return total[t] - s.used[t]; }
  void minext(const BState& s, double* m) const {
    m[0] = m[1] = m[2] = 1e18;
    for (size_t t = 0; t < BT.size(); ++t) if (rem(s, (int)t) > 0) for (auto& o : BT[t].ors) for (int a = 0; a < 3; ++a) m[a] = std::min(m[a], o[a]);
  }
  BState start() const { BState s; s.ct = ct; s.used.assign(BT.size(), 0); s.sp.push_back({0, 0, 0, c->L, c->W, c->H}); return s; }

  double space_key(const Space& p) const {
    switch (BP.space) {
      case 1: return p.z0 * 1e8 + p.x0 * 1e3 + p.y0 * 1e-2;
      case 2: { double dy = std::min(p.y0, c->W - p.y1), dz = p.z0, dx = p.x0;  // front corners: x from front wall
        double a[3] = {dx, dy, dz}; std::sort(a, a + 3); return a[0] * 1e8 + a[1] * 1e3 + a[2] * 1e-2 + dx * 1e-6; }
      default: return p.x0 * 1e8 + p.z0 * 1e3 + p.y0 * 1e-2;
    }
  }
  int pick_space(const BState& s) const {
    int bi = -1; double bk = 1e300;
    for (size_t i = 0; i < s.sp.size(); ++i) { double k = space_key(s.sp[i]); if (k < bk) { bk = k; bi = (int)i; } }
    return bi;
  }

  // supported area of rectangle [x0,x1)x[y0,y1) at height z by tops of placed blocks
  double support(const BState& s, double x0, double x1, double y0, double y1, double z) const {
    if (z < 1e-6) return (x1 - x0) * (y1 - y0);
    double a = 0;
    for (auto& b : s.bl) {
      if (std::fabs(b.z + b.bz * b.nz - z) > 1e-3) continue;
      double ix = std::min(x1, b.x + b.bx * b.nx) - std::max(x0, b.x), iy = std::min(y1, b.y + b.by * b.ny) - std::max(y0, b.y);
      if (ix > 0 && iy > 0) a += ix * iy;
    }
    return a;
  }
  // feasibility of a block anchored at (x,y,z): weight, support of every bottom box, load on supporters, LIFO, hazmat
  bool feasible(const BState& s, const Cand& k, double x, double y, double z, double* kgout) const {
    const BType& T = BT[k.t]; const auto& o = T.ors[k.o]; int n = k.nx * k.ny * k.nz;
    double kg = T.pre[s.used[k.t] + n] - T.pre[s.used[k.t]];
    if (s.kg + kg > c->max_kg + 1e-6) return false;
    if (k.nz > 1 && IT[T.items[s.used[k.t]]].kg > T.max_top + 1e-6) return false;  // box on box inside the block
    double X1 = x + o[0] * k.nx, Y1 = y + o[1] * k.ny;
    if (z > 1e-6) {
      double full = (X1 - x) * (Y1 - y), sa = support(s, x, X1, y, Y1, z);
      if (sa < P.min_support * full - 1e-6) return false;
      if (sa < full * (1 - 1e-9))
        for (int i = 0; i < k.nx; ++i) for (int j = 0; j < k.ny; ++j) {
          double bx0 = x + o[0] * i, by0 = y + o[1] * j;
          if (support(s, bx0, bx0 + o[0], by0, by0 + o[1], z) < P.min_support * o[0] * o[1] - 1e-6) return false;
        }
      if (anyload) {
        double heaviest = IT[T.items[s.used[k.t]]].kg;
        for (auto& b : s.bl) {
          if (std::fabs(b.z + b.bz * b.nz - z) > 1e-3) continue;
          if (!ovl(x, X1, b.x, b.x + b.bx * b.nx) || !ovl(y, Y1, b.y, b.y + b.by * b.ny)) continue;
          double add = heaviest * std::max(1.0, (b.bx * b.by) / (o[0] * o[1]));
          if (b.load + add > BT[b.t].max_top + 1e-6) return false;
        }
      }
    }
    double Z1 = z + o[2] * k.nz;
    if (multistop && P.lifo)
      for (auto& b : s.bl) {
        if (!ovl(y, Y1, b.y, b.y + b.by * b.ny) || !ovl(z, Z1, b.z, b.z + b.bz * b.nz)) continue;
        if (BT[b.t].stop > T.stop && b.x >= X1 - 1e-6) return false;
        if (BT[b.t].stop < T.stop && b.x + b.bx * b.nx <= x + 1e-6) return false;
      }
    if (anyhaz && P.hazmat_sep > 0 && !T.hazmat.empty())
      for (auto& b : s.bl) if (!BT[b.t].hazmat.empty() && BT[b.t].hazmat != T.hazmat) {
        double gx = std::max(b.x - X1, x - (b.x + b.bx * b.nx)); if (gx < P.hazmat_sep) return false; }
    if (kgout) *kgout = kg;
    return true;
  }

  // a mixed column = part A (k.t) at the space corner + part B (k.t2, same footprint) directly on top of it
  static Cand partA(const Cand& k) { Cand a = k; a.t2 = -1; a.nz2 = 0; return a; }
  static Cand partB(const Cand& k) { return Cand{k.t2, k.o2, k.nx, k.ny, k.nz2, 0, 0}; }
  bool feasible_any(const BState& s, const Cand& k, double x, double y, double z, double* kgout) const {
    if (k.t2 < 0) return feasible(s, k, x, y, z, kgout);
    double ka, kb; Cand a = partA(k), b = partB(k);
    if (!feasible(s, a, x, y, z, &ka)) return false;
    // B rests fully on A (same footprint): check weight, A's top load, LIFO / hazmat for B's z range via feasible() on z above A
    const BType& A = BT[a.t]; const BType& B = BT[b.t];
    double kgB = B.pre[s.used[b.t] + b.nx * b.ny * b.nz] - B.pre[s.used[b.t]];
    if (s.kg + ka + kgB > c->max_kg + 1e-6) return false;
    double above_per_col = IT[B.items[s.used[b.t]]].kg * b.nz;  // heaviest B boxes, conservatively
    if (above_per_col > A.max_top + 1e-6) return false;
    if (multistop && P.lifo) {
      const auto& oa = A.ors[a.o]; const auto& ob = B.ors[b.o];
      double X1 = x + ob[0] * b.nx, Y1 = y + ob[1] * b.ny, Z0 = z + oa[2] * a.nz, Z1 = Z0 + ob[2] * b.nz;
      for (auto& q : s.bl) {
        if (!ovl(y, Y1, q.y, q.y + q.by * q.ny) || !ovl(Z0, Z1, q.z, q.z + q.bz * q.nz)) continue;
        if (BT[q.t].stop > B.stop && q.x >= X1 - 1e-6) return false;
        if (BT[q.t].stop < B.stop && q.x + q.bx * q.nx <= x + 1e-6) return false;
      }
    }
    if (b.nz > 1 && IT[B.items[s.used[b.t]]].kg > B.max_top + 1e-6) return false;
    (void)kb;
    if (kgout) *kgout = ka + kgB;
    return true;
  }

  void candidates(const BState& s, const Space& p, std::vector<Cand>& out) const {
    out.clear(); double sx = p.x1 - p.x0, sy = p.y1 - p.y0, sz = p.z1 - p.z0, svol = sx * sy * sz;
    int maxstop = -1; if (multistop && P.lifo) for (size_t t = 0; t < BT.size(); ++t) if (rem(s, (int)t) > 0) maxstop = std::max(maxstop, BT[t].stop);
    double maxbig = 0, maxden = 0; for (size_t t = 0; t < BT.size(); ++t) if (rem(s, (int)t) > 0) { maxbig = std::max(maxbig, BT[t].vol); maxden = std::max(maxden, BT[t].dens); }
    // type of the block directly below / in front (for the same-spec preference)
    int below = -1;
    for (auto& b : s.bl) if (std::fabs(b.z + b.bz * b.nz - p.z0) < 1e-3 && ovl(p.x0, p.x0 + 1, b.x, b.x + b.bx * b.nx) && ovl(p.y0, p.y0 + 1, b.y, b.y + b.by * b.ny)) below = b.t;
    for (size_t t = 0; t < BT.size(); ++t) {
      int r = rem(s, (int)t); if (r <= 0) continue;
      if (maxstop >= 0 && BT[t].stop != maxstop) continue;  // LIFO phases: last stop first
      for (size_t oi = 0; oi < BT[t].ors.size(); ++oi) {
        const auto& o = BT[t].ors[oi];
        int mx = (int)((sx + 1e-6) / o[0]), my = (int)((sy + 1e-6) / o[1]), mz = (int)((sz + 1e-6) / o[2]);
        if (mx < 1 || my < 1 || mz < 1) continue;
        if (BT[t].fragile || BT[t].max_top <= 0) mz = 1;
        auto kfit = [&](const Knap& k, int m, double d, double len) {  // count whose leftover is best filled
          int bc = m; double bf = -1;
          for (int q = m; q >= 1 && q >= m - 3; --q) { double f = q * d + knap_fill(k, len - q * d); if (f > bf + 1e-6) { bf = f; bc = q; } }
          return bc; };
        int ys[2] = {my, kfit(ky, my, o[1], sy)}, zs[2] = {mz, kfit(kz, mz, o[2], sz)};
        std::vector<int> xs; if (BP.depth != 2) xs.push_back(1); if (BP.depth != 1) xs.push_back(mx);
        std::set<std::array<int,3>> seen;
        for (int yi = 0; yi < 2; ++yi) for (int zi = 0; zi < 2; ++zi) for (int nx0 : xs) {
          int ny = ys[yi], nz = zs[zi], nx = nx0;
          // honour the available count: shrink depth first, then height, then width
          if ((long)nx * ny * nz > r) { nx = std::max(1, r / (ny * nz)); }
          if ((long)nx * ny * nz > r) { nz = std::max(1, r / ny); nx = 1; }
          if ((long)nx * ny * nz > r) { ny = r; nz = 1; nx = 1; }
          if (!seen.insert({nx, ny, nz}).second) continue;
          double bx = nx * o[0], by = ny * o[1], bz = nz * o[2], v = bx * by * bz;
          Cand k{(int)t, (int)oi, nx, ny, nz, 0, v};
          double ly = sy - by, lz = sz - bz;
          double waste = ((ly - knap_fill(ky, ly)) / c->W + (lz - knap_fill(kz, lz)) / c->H);
          k.score = BP.w_vol * v + BP.w_fill * v / svol * 1e9 + BP.w_yz * (by * bz) / (sy * sz) * 1e9 + BP.w_xy * (bx * by) / (sx * sy) * 1e9
                  + BP.w_big * BT[t].vol / maxbig * 1e9 + BP.w_heavy * (maxden > 0 ? BT[t].dens / maxden : 0) * (1 - p.z0 / c->H) * 1e9
                  - BP.w_waste * waste * 1e9 + BP.w_same * ((int)t == below ? 1e9 : 0);
          if (noise > 0) k.score *= 1 + noise * (std::uniform_real_distribution<double>(-1, 1)(rng));
          out.push_back(k);
        }
      }
    }
    // mixed-spec columns: same footprint (dx, dy), A below B, heights chosen to fill the space height best
    if (BP.mixed) {
      size_t npure = out.size();
      for (size_t ci = 0; ci < npure; ++ci) {
        const Cand k = out[ci]; const BType& A = BT[k.t]; const auto& oa = A.ors[k.o];
        if (A.fragile || A.max_top <= 0 || !A.hazmat.empty()) continue;
        double hA = oa[2], fillA = k.nz * hA; if (sz - fillA < 1e-6) continue;
        for (size_t u = 0; u < BT.size(); ++u) {
          if ((int)u == k.t) continue;
          int ru = rem(s, (int)u); if (ru <= 0) continue;
          const BType& U = BT[u]; if (!U.hazmat.empty() || U.stop != A.stop) continue;
          for (size_t ou = 0; ou < U.ors.size(); ++ou) {
            const auto& ob = U.ors[ou]; if (std::fabs(ob[0] - oa[0]) > 1 || std::fabs(ob[1] - oa[1]) > 1) continue;
            int cols = k.nx * k.ny; int maxA = std::min(k.nz, rem(s, k.t) / cols);
            double bestf = fillA; int bA = 0, bB = 0;
            for (int na = std::max(1, maxA - 3); na <= maxA; ++na) {
              int nb = (int)((sz - na * hA + 1e-6) / ob[2]); nb = std::min(nb, ru / cols);
              if (U.fragile || U.max_top <= 0) nb = std::min(nb, 1);
              if (nb < 1) continue;
              double f = na * hA + nb * ob[2];
              if (f > bestf + 1e-6) { bestf = f; bA = na; bB = nb; }
            }
            if (!bA) continue;
            Cand m{k.t, k.o, k.nx, k.ny, bA, 0, 0, (int)u, (int)ou, bB};
            double bx = k.nx * oa[0], by = k.ny * oa[1], bz = bestf; m.vol = cols * (bA * A.vol + bB * U.vol);
            double ly = sy - by, lz = sz - bz;
            double waste = ((ly - knap_fill(ky, ly)) / c->W + (lz - knap_fill(kz, lz)) / c->H);
            m.score = BP.w_vol * m.vol + BP.w_fill * m.vol / svol * 1e9 + BP.w_yz * (by * bz) / (sy * sz) * 1e9 + BP.w_xy * (bx * by) / (sx * sy) * 1e9
                    + BP.w_big * A.vol / maxbig * 1e9 + BP.w_heavy * (maxden > 0 ? A.dens / maxden : 0) * (1 - p.z0 / c->H) * 1e9
                    - BP.w_waste * waste * 1e9 + BP.w_same * (k.t == below ? 1e9 : 0);
            if (noise > 0) m.score *= 1 + noise * (std::uniform_real_distribution<double>(-1, 1)(rng));
            out.push_back(m);
          }
        }
      }
    }
    std::sort(out.begin(), out.end(), [](const Cand& a, const Cand& b) { return a.score > b.score; });
  }

  void place(BState& s, int si, const Cand& k, double kg) const {
    if (k.t2 >= 0) {  // mixed column: A at the corner, then B in the space directly above A
      const Space p = s.sp[si]; Cand a = partA(k), b = partB(k); const auto& oa = BT[a.t].ors[a.o]; const auto& ob = BT[b.t].ors[b.o];
      a.vol = a.nx * a.ny * a.nz * BT[a.t].vol; b.vol = b.nx * b.ny * b.nz * BT[b.t].vol;
      double ka = BT[a.t].pre[s.used[a.t] + a.nx * a.ny * a.nz] - BT[a.t].pre[s.used[a.t]];
      place1(s, si, a, ka);
      double zt = p.z0 + a.nz * oa[2], X1 = p.x0 + b.nx * ob[0], Y1 = p.y0 + b.ny * ob[1], Z1 = zt + b.nz * ob[2];
      for (size_t j = 0; j < s.sp.size(); ++j) {
        const Space& q = s.sp[j];
        if (std::fabs(q.x0 - p.x0) < 1e-3 && std::fabs(q.y0 - p.y0) < 1e-3 && std::fabs(q.z0 - zt) < 1e-3 && q.x1 >= X1 - 1e-6 && q.y1 >= Y1 - 1e-6 && q.z1 >= Z1 - 1e-6) {
          place1(s, (int)j, b, kg - ka); return; }
      }
      return;  // cannot happen (the split always leaves the space above A); B is simply not placed
    }
    place1(s, si, k, kg);
  }
  void place1(BState& s, int si, const Cand& k, double kg) const {
    const Space p = s.sp[si]; const auto& o = BT[k.t].ors[k.o];
    PBlock b{k.t, k.o, k.nx, k.ny, k.nz, s.used[k.t], p.x0, p.y0, p.z0, o[0], o[1], o[2], kg, 0};
    if (p.z0 > 1e-6 && anyload) {
      double heaviest = IT[BT[k.t].items[s.used[k.t]]].kg;
      for (auto& q : s.bl) if (std::fabs(q.z + q.bz * q.nz - p.z0) < 1e-3 && ovl(b.x, b.x + b.bx * b.nx, q.x, q.x + q.bx * q.nx) && ovl(b.y, b.y + b.by * b.ny, q.y, q.y + q.by * q.ny))
        q.load += heaviest * std::max(1.0, (q.bx * q.by) / (o[0] * o[1]));
    }
    s.used[k.t] += k.nx * k.ny * k.nz; s.vol += k.vol; s.kg += kg; s.bl.push_back(b);
    double X0 = b.x, X1 = b.x + b.bx * b.nx, Y0 = b.y, Y1 = b.y + b.by * b.ny, Z0 = b.z, Z1 = b.z + b.bz * b.nz;
    std::vector<Space> ns; ns.reserve(s.sp.size() + 8);
    double m[3]; minext(s, m);
    auto ok = [&](const Space& q) { return q.x1 - q.x0 >= m[0] - 1e-6 && q.y1 - q.y0 >= m[1] - 1e-6 && q.z1 - q.z0 >= m[2] - 1e-6; };
    for (auto& q : s.sp) {
      if (!(ovl(q.x0, q.x1, X0, X1) && ovl(q.y0, q.y1, Y0, Y1) && ovl(q.z0, q.z1, Z0, Z1))) { if (ok(q)) ns.push_back(q); continue; }
      Space r;
      if (X0 > q.x0 + 1e-6) { r = q; r.x1 = X0; if (ok(r)) ns.push_back(r); }
      if (X1 < q.x1 - 1e-6) { r = q; r.x0 = X1; if (ok(r)) ns.push_back(r); }
      if (Y0 > q.y0 + 1e-6) { r = q; r.y1 = Y0; if (ok(r)) ns.push_back(r); }
      if (Y1 < q.y1 - 1e-6) { r = q; r.y0 = Y1; if (ok(r)) ns.push_back(r); }
      if (Z0 > q.z0 + 1e-6) { r = q; r.z1 = Z0; if (ok(r)) ns.push_back(r); }
      if (Z1 < q.z1 - 1e-6) { r = q; r.z0 = Z1; if (ok(r)) ns.push_back(r); }
    }
    // drop spaces contained in another one
    std::vector<char> dead(ns.size(), 0);
    for (size_t i = 0; i < ns.size(); ++i) if (!dead[i]) for (size_t j = 0; j < ns.size(); ++j) if (i != j && !dead[j]) {
      const Space &a = ns[i], &bb = ns[j];
      if (a.x0 >= bb.x0 - 1e-6 && a.y0 >= bb.y0 - 1e-6 && a.z0 >= bb.z0 - 1e-6 && a.x1 <= bb.x1 + 1e-6 && a.y1 <= bb.y1 + 1e-6 && a.z1 <= bb.z1 + 1e-6) { dead[i] = 1; break; }
    }
    s.sp.clear(); for (size_t i = 0; i < ns.size(); ++i) if (!dead[i]) s.sp.push_back(ns[i]);
  }

  // ranked feasible candidates for the selected space; spaces that cannot take anything are discarded
  int next(BState& s, std::vector<Cand>& feas, std::vector<double>& kgs, int want) const {
    std::vector<Cand> cs;
    while (!s.sp.empty()) {
      int si = pick_space(s); candidates(s, s.sp[si], cs); feas.clear(); kgs.clear();
      for (auto& k : cs) { double kg; if (feasible_any(s, k, s.sp[si].x0, s.sp[si].y0, s.sp[si].z0, &kg)) { feas.push_back(k); kgs.push_back(kg); if ((int)feas.size() >= want) break; } }
      if (!feas.empty()) return si;
      s.sp.erase(s.sp.begin() + si);
    }
    return -1;
  }
  void greedy(BState& s) const { std::vector<Cand> f; std::vector<double> kg; int si; while ((si = next(s, f, kg, 1)) >= 0) place(s, si, f[0], kg[0]); }
  bool all_in(const BState& s) const { for (size_t t = 0; t < BT.size(); ++t) if (rem(s, (int)t) > 0) return false; return true; }

  // one lookahead pass of width w; returns the pass state, updates best with every completion
  BState pass(int w, BState& best, double deadline_ms, const std::function<double()>& now, int* evals, bool* saturated, bool* timeout) const {
    BState s = start(); std::vector<Cand> f; std::vector<double> kg;
    while (true) {
      int si = next(s, f, kg, w); if (si < 0) break;
      if ((int)f.size() >= w) *saturated = false;
      int bk = 0; double bv = -1;
      if (f.size() > 1) for (size_t i = 0; i < f.size(); ++i) {
        if (now() > deadline_ms) { *timeout = true; break; }
        BState t = s; place(t, si, f[i], kg[i]); greedy(t); if (evals) ++*evals;
        if (t.vol > best.vol + 1e-6) best = t;
        if (t.vol > bv + 1e-6) { bv = t.vol; bk = (int)i; }
      }
      if (*timeout) break;
      place(s, si, f[bk], kg[bk]);
    }
    if (s.vol > best.vol + 1e-6) best = s;
    return s;
  }
  // lookahead search: iterative widening until it saturates, then randomized restarts until the deadline
  BState search(double deadline_ms, const std::function<double()>& now, int* evals) const {
    noise = 0; BState best = start(); greedy(best); if (evals) ++*evals;
    if (all_in(best)) return best;
    bool timeout = false;
    for (int w = BP.width > 0 ? BP.width : 2; !timeout; w *= 2) {
      bool sat = true; pass(w, best, deadline_ms, now, evals, &sat, &timeout);
      if (all_in(best) || BP.width > 0 || now() > deadline_ms) return best;
      if (sat || w >= BP.maxw) break;
    }
    rng.seed(P.seed);
    while (!timeout && now() < deadline_ms && !all_in(best) && BP.noise > 0) {
      noise = BP.noise; bool sat = true; pass(BP.rwidth, best, deadline_ms, now, evals, &sat, &timeout);
    }
    noise = 0;
    return best;
  }
};

// expand a state into the old Bin / Placed representation (box-level, loading sequence = block order, bottom-up)
static Bin to_bin(const BState& s, std::vector<char>& usedItem, int& seq) {
  Bin b; b.ctype = s.ct;
  // assign real items: block k used items [first, first+n) of its type
  for (auto& k : s.bl) {
    const BType& T = BT[k.t]; int q = 0;
    for (int iz = 0; iz < k.nz; ++iz) for (int ix = 0; ix < k.nx; ++ix) for (int iy = 0; iy < k.ny; ++iy) {
      int ii = T.items[k.first + q++];
      b.p.push_back({ii, k.x + ix * k.bx, k.y + iy * k.by, k.z + iz * k.bz, k.bx, k.by, k.bz, 0, seq++});
      b.kg += IT[ii].kg; b.vol += IT[ii].l * IT[ii].w * IT[ii].h; usedItem[ii] = 1;  // nominal volume
    }
  }
  return b;
}

// multi-container driver: per bin choose type (cheapest type that takes everything left, otherwise best volume/cost)
static Sol block_solve(double time_ms, const std::function<double()>& now, int* evals) {
  Sol sol; std::vector<char> used(IT.size(), 0); int seq = 0; std::vector<int> cnt(CT.size(), 0);
  double t0 = now();
  while (BP.maxbins <= 0 || (int)sol.bins.size() < BP.maxbins) {
    std::vector<int> left; for (size_t i = 0; i < IT.size(); ++i) if (!used[i]) left.push_back((int)i);
    if (left.empty()) break;
    build_types(left);
    std::vector<int> avail(BT.size()); for (size_t t = 0; t < BT.size(); ++t) avail[t] = (int)BT[t].items.size();
    double lv = 0, lkg = 0; for (int i : left) { lv += IT[i].l * IT[i].w * IT[i].h * std::pow(1 - BP.squeeze, 3); lkg += IT[i].kg; }
    double maxcap = 0; for (auto& c : CT) maxcap = std::max(maxcap, c.L * c.W * c.H);
    int nb = BP.maxbins == 1 ? 1 : std::max(1, (int)std::ceil(lv / (0.8 * maxcap)));
    double budget = std::max(50.0, (time_ms - (now() - t0)) / nb);
    // greedy probe of every type
    struct Opt { int c; BState s; bool all; double val; };
    std::vector<Opt> opts;
    for (size_t c = 0; c < CT.size(); ++c) {
      if (CT[c].limit >= 0 && cnt[c] >= CT[c].limit) continue;
      Engine e; e.init((int)c, avail); BState s = e.start(); e.greedy(s); if (evals) ++*evals;
      if (s.bl.empty()) continue;
      opts.push_back({(int)c, s, e.all_in(s), s.vol / CT[c].cost});
    }
    if (opts.empty()) break;
    int pick = -1;
    for (size_t i = 0; i < opts.size(); ++i) if (opts[i].all && (pick < 0 || CT[opts[i].c].cost < CT[opts[pick].c].cost)) pick = (int)i;
    // types whose capacity could take everything left: search them cheapest first
    std::vector<int> ord(opts.size()); std::iota(ord.begin(), ord.end(), 0);
    std::sort(ord.begin(), ord.end(), [&](int a, int b) { return CT[opts[a].c].cost < CT[opts[b].c].cost; });
    double tslice_end = now() + budget;
    for (int i : ord) {
      if (pick >= 0 && CT[opts[i].c].cost >= CT[opts[pick].c].cost) break;
      const CType& c = CT[opts[i].c];
      if (c.L * c.W * c.H < lv - 1e-6 || c.max_kg < lkg - 1e-6) continue;
      Engine e; e.init(opts[i].c, avail);
      BState s = e.search(std::min(tslice_end, now() + budget * 0.7), now, evals);
      if (s.vol > opts[i].s.vol) opts[i].s = s;
      if (e.all_in(s)) { opts[i].all = true; pick = i; break; }
    }
    if (pick < 0) {  // nothing takes all: best volume per cost, then improve it with the rest of the slice
      for (size_t i = 0; i < opts.size(); ++i) if (pick < 0 || opts[i].s.vol / CT[opts[i].c].cost > opts[pick].s.vol / CT[opts[pick].c].cost) pick = (int)i;
      Engine e; e.init(opts[pick].c, avail);
      BState s = e.search(std::max(now() + 20, tslice_end), now, evals);
      if (s.vol > opts[pick].s.vol) opts[pick].s = s;
    }
    BState& s = opts[pick].s;
    // map type-local "first" indices to items, mark used
    Bin b = to_bin(s, used, seq);
    if (b.p.empty()) break;
    cnt[opts[pick].c]++; sol.cost += CT[opts[pick].c].cost; sol.bins.push_back(std::move(b));
  }
  for (size_t i = 0; i < IT.size(); ++i) if (!used[i]) sol.unplaced.push_back((int)i);
  double last_fill = sol.bins.empty() ? 0 : sol.bins.back().vol / (CT[sol.bins.back().ctype].L * CT[sol.bins.back().ctype].W * CT[sol.bins.back().ctype].H);
  sol.score = sol.unplaced.size() * 1e9 + sol.cost * 1e3 + last_fill;
  return sol;
}
