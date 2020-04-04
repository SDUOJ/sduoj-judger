#include<bits/stdc++.h>
using namespace std;
#define MAXP	10000005
#define MAXN	100005
#define MAXLOG	105
#define ALPHA	0.8
template <typename T> void read(T &x) {
	x = 0; int f = 1;
	char c = getchar();
	for (; !isdigit(c); c = getchar()) if (c == '-') f = -f;
	for (; isdigit(c); c = getchar()) x = x * 10 + c - '0';
	x *= f;
}
template <typename T> void write(T x) {
	if (x < 0) x = -x, putchar('-');
	if (x > 9) write(x / 10);
	putchar(x % 10 + '0');
}
template <typename T> void writeln(T x) {
	write(x);
	puts("");
}
struct DivideAndConquerTree {
	struct ScapeGoatTree {
		struct Node {
			int index, size;
			int lc, rc;
		} a[MAXP];
		int SonRoot[MAXN];
		int RootRoot[MAXN];
		int top, mem[MAXP];
		int tot, tmp[MAXN];
		void init(int tot) {
			top = 0;
			for (int i = tot; i >= 1; i--)
				mem[++top] = i;
		}
		int new_node(int val) {
			int tmp = mem[top--];
			a[tmp] = (Node) {val, 1, 0, 0};
			return tmp;
		}
		void dfs(int pos) {
			mem[++top] = pos;
			if (a[pos].lc) dfs(a[pos].lc);
			tmp[++tot] = a[pos].index;
			if (a[pos].rc) dfs(a[pos].rc);
		}
		int rebuild(int l, int r) {
			if (l == r) return new_node(tmp[l]);
			int mid = (l + r) / 2, ans = new_node(tmp[mid]);
			a[ans].size = r - l + 1;
			if (mid > l) a[ans].lc = rebuild(l, mid - 1);
			if (mid < r) a[ans].rc = rebuild(mid + 1, r);
			return ans;
		}
		int Rebuild(int root, int val) {
			tot = 0, dfs(root);
			bool flg = true;
			for (int i = 1; i <= tot; i++)
				if (tmp[i] >= val) {
					tot++;
					for (int j = tot; j >= i + 1; j--)
						tmp[j] = tmp[j - 1];
					tmp[i] = val;
					flg = false;
					break;
				}
			if (flg) tmp[++tot] = val;
			return rebuild(1, tot);
		}
		void insert(int &pos, int val) {
			if (pos == 0) {
				pos = new_node(val);
				return;
			}
			a[pos].size++;
			if (val < a[pos].index) {
				if (a[a[pos].lc].size + 1 > a[pos].size * ALPHA + 1) {
					pos = Rebuild(pos, val);
				} else insert(a[pos].lc, val);
			} else {
				if (a[a[pos].rc].size + 1 > a[pos].size * ALPHA + 1) {
					pos = Rebuild(pos, val);
				} else insert(a[pos].rc, val);
			}
		}
		void restore(int pos) {
			mem[++top] = pos;
			if (a[pos].lc) restore(a[pos].lc);
			if (a[pos].rc) restore(a[pos].rc);
		}
		int query(int pos, int val) {
			if (pos == 0) return 0;
			if (val < a[pos].index) return query(a[pos].lc, val);
			else return query(a[pos].rc, val) + a[a[pos].lc].size + 1;
		}
		void RootClear(int pos) {
			if (RootRoot[pos]) restore(RootRoot[pos]);
			RootRoot[pos] = 0;
		}
		void SonClear(int pos) {
			if (SonRoot[pos]) restore(SonRoot[pos]);
			SonRoot[pos] = 0;
		}
		void RootInsert(int pos, int val) {
			insert(RootRoot[pos], val);
		}
		void SonInsert(int pos, int val) {
			insert(SonRoot[pos], val);
		}
		int RootQuery(int pos, int val) {
			return query(RootRoot[pos], val);
		}
		int SonQuery(int pos, int val) {
			return query(SonRoot[pos], val);
		}
		void give(int from, int to) {
			SonRoot[to] = SonRoot[from];
			SonRoot[from] = 0;
		}
	} SGT;
	struct Tree {
		int depth[MAXN], father[MAXN];
		int dist[MAXN][MAXLOG], size[MAXN];
		unsigned home[MAXN];
		vector <int> a[MAXN];
	} T;
	struct edge {int dest, len; };
	int n, cnt, root, r[MAXN];
	vector <edge> a[MAXN];
	int size[MAXN], weight[MAXN];
	bool mark[MAXN];
	void chkmax(int &x, int y) {
		x = max(x, y);
	}
	void init(int x, int y) {
		T.a[0].push_back(0);
		T.depth[1] = 1;
		n = x; r[1] = y;
		weight[0] = n + 1;
		SGT.init(MAXP - 1);
		SGT.RootInsert(1, -y);
	}
	void dfs(int pos) {
		cnt++;
		mark[pos] = true;
		for (unsigned i = 0; i < T.a[pos].size(); i++)
			dfs(T.a[pos][i]);
	}
	void getroot(int pos, int fa, int cnt) {
		size[pos] = 1; weight[pos] = 0;
		for (unsigned i = 0; i < a[pos].size(); i++)
			if (a[pos][i].dest != fa && mark[a[pos][i].dest]) {
				getroot(a[pos][i].dest, pos, cnt);
				size[pos] += size[a[pos][i].dest];
				chkmax(weight[pos], size[a[pos][i].dest]);
			}
		chkmax(weight[pos], cnt - size[pos]);
		if (weight[pos] < weight[root]) root = pos;
	}
	void recalsize(int pos, int fa) {
		size[pos] = 1;
		for (unsigned i = 0; i < a[pos].size(); i++)
			if (a[pos][i].dest != fa && mark[a[pos][i].dest]) {
				recalsize(a[pos][i].dest, pos);
				size[pos] += size[a[pos][i].dest];
			}
	}
	void recal(int pos, int fa, int from, int fromdepth, int dist) {
		T.size[from]++;
		T.dist[pos][fromdepth] = dist;
		SGT.RootInsert(from, dist - r[pos]);
		SGT.SonInsert(root, dist - r[pos]);
		for (unsigned i = 0; i < a[pos].size(); i++)
			if (a[pos][i].dest != fa && mark[a[pos][i].dest]) {
				recal(a[pos][i].dest, pos, from, fromdepth, dist + a[pos][i].len);
			}
	}
	void work(int pos, int depth, int tot) {
		T.a[pos].clear();
		mark[pos] = false;
		T.depth[pos] = depth;
		SGT.RootClear(pos);
		SGT.RootInsert(pos, -r[pos]);
		recalsize(pos, 0);
		T.size[pos] = 1;
		T.dist[pos][depth] = 0;
		for (unsigned i = 0; i < a[pos].size(); i++)
			if (mark[a[pos][i].dest]) {
				root = 0;
				getroot(a[pos][i].dest, 0, size[a[pos][i].dest]);
				SGT.SonClear(root);
				recal(a[pos][i].dest, pos, pos, depth, a[pos][i].len);
			}
		for (unsigned i = 0; i < a[pos].size(); i++)
			if (mark[a[pos][i].dest]) {
				root = 0;
				getroot(a[pos][i].dest, 0, size[a[pos][i].dest]);
				T.father[root] = pos;
				T.a[pos].push_back(root);
				T.home[root] = T.a[pos].size() - 1;
				work(root, depth + 1, size[a[pos][i].dest]);
			}
	}
	void rebuild(int pos) {
		cnt = 0;
		dfs(pos);
		root = 0;
		getroot(pos, 0, cnt);
		T.a[T.father[pos]][T.home[pos]] = root;
		T.father[root] = T.father[pos];
		SGT.give(pos, root);
		work(root, T.depth[pos], cnt);
	}
	int insert(int pos, int x, int y, int z) {
		a[pos].push_back((edge) {x, y});
		a[x].push_back((edge) {pos, y});
		r[pos] = z;
		T.size[pos] = 1;
		T.father[pos] = x;
		T.a[x].push_back(pos);
		T.depth[pos] = T.depth[x] + 1;
		T.home[pos] = T.a[x].size() - 1;
		T.dist[pos][T.depth[pos]] = 0;
		SGT.RootInsert(pos, -z);
		int now = pos, last = now, Reroot = 0;
		for (int i = T.depth[pos] - 1; i >= 1; i--) {
			last = now;
			now = T.father[now];
			T.size[now]++;
			T.dist[pos][i] = T.dist[x][i] + y;
			SGT.RootInsert(now, T.dist[pos][i] - z);
			SGT.SonInsert(last, T.dist[pos][i] - z);
			if (T.size[last] > T.size[now] * ALPHA + 1) Reroot = now;
		}
		if (Reroot) rebuild(Reroot);
		int ans = SGT.RootQuery(pos, z) - 1;
		now = pos, last = now;
		for (int i = T.depth[pos] - 1; i >= 1; i--) {
			last = now;
			now = T.father[now];
			ans += SGT.RootQuery(now, z - T.dist[pos][i]);
			ans -= SGT.SonQuery(last, z - T.dist[pos][i]);
		}
		return ans;
	}
} DACT;
int main() {
	int t; read(t);
	int n; read(n);
	long long lastans = 0;
	read(t), read(t), read(t);
	DACT.init(n, t);
	writeln(lastans);
	for (int i = 2; i <= n; i++) {
		int x, y, z;
		read(x), read(y), read(z);
		x ^= (lastans % 1000000000);
		lastans += DACT.insert(i, x, y, z);
		writeln(lastans);
	}
	return 0;
}