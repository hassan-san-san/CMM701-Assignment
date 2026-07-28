# pip install pandas numpy matplotlib seaborn leidenalg igraph networkx scikit-learn openpyxl scikit-posthocs

import pandas as pd
import numpy as np
import ast
from itertools import combinations
from collections import defaultdict
import igraph as ig
import leidenalg as la
import networkx as nx
from sklearn.metrics import adjusted_rand_score
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import seaborn as sns
from scipy import stats
import scikit_posthocs as sp
import warnings
warnings.filterwarnings("ignore")


DATA_PATH = "C:/Uni/Uni Masters/Dissertation/output/steam_dataset.csv"
MIN_PAIR_FREQ = 5
MEMBERSHIP_THRESH = 0.15
N_LEIDEN_RUNS = 10
TOP_TAGS_HEATMAP = 50


# load it in
df = pd.read_csv(DATA_PATH)
print("games loaded:", str(len(df)))

# total_reviews doesnt match pos + neg, known issue with the API pull
df["totalReviewCount"] = df["positive_reviews"] + df["negative_reviews"]
df["review_score"] = pd.to_numeric(df["review_score"], errors="coerce")

df = df.dropna(subset=["tags", "review_score"])
df = df[df["totalReviewCount"] > 0].reset_index(drop=True)
print("after dropping unusable rows:", str(len(df)))
print("")


# tags come in as a dict string e.g.
# ast handles this cleanly, tried json.loads first but it doesnt like single quotes
def parseTags(raw):
    try:
        parsed = ast.literal_eval(str(raw))
        return {str(k): int(v) for k, v in parsed.items() if int(v) > 0}
    except:
        return {}

df["tagsParsed"] = df["tags"].apply(parseTags)
df = df[df["tagsParsed"].map(len) > 0].reset_index(drop=True)

allTags = set()
for td in df["tagsParsed"]:
    allTags.update(td.keys())

tagList   = sorted(list(allTags))
tagToIdx  = {tag: i for i, tag in enumerate(tagList)}
nTags     = len(tagList)

print("unique tags:", str(nTags))
print("usable games:", str(len(df)))
print("")


# EDA - just want a rough feel for the data before going further
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle("Steam Dataset Overview", fontsize=13)

axes[0,0].hist(df["review_score"], bins=50, color="#4C72B0", edgecolor="white")
axes[0,0].set_title("Review Score Distribution")
axes[0,0].set_xlabel("Score")
axes[0,0].set_ylabel("Count")

# log scale because a handful of games have like 500k reviews and ruin the axis
axes[0,1].hist(np.log10(df["totalReviewCount"]+1), bins=50, color="#DD8452", edgecolor="white")
axes[0,1].set_title("Review Count (log10)")
axes[0,1].set_xlabel("log10(count)")

axes[1,0].hist(df["tagsParsed"].map(len), bins=40, color="#55A868", edgecolor="white")
axes[1,0].set_title("Tags Per Game")
axes[1,0].set_xlabel("n tags")

tagFreq = defaultdict(int)
for td in df["tagsParsed"]:
    for t in td:
        tagFreq[t] += 1

top20 = sorted(tagFreq.items(), key=lambda x: x[1], reverse=True)[:20]
axes[1,1].barh([t[0] for t in top20][::-1], [t[1] for t in top20][::-1], color="#C44E52")
axes[1,1].set_title("Top 20 Tags")

plt.tight_layout()
plt.savefig("eda_overview.png", dpi=150, bbox_inches="tight")
plt.show()


# co-occurrence - normalise within each game first so popular games
# dont dominate just because more people tagged them
print("building co-occurrence, takes a minute or two...")

tagTotalWeight = defaultdict(float)
coOcc          = defaultdict(float)
nGames         = 0

for td in df["tagsParsed"]:
    total = sum(td.values())
    if total == 0:
        continue

    normed = {t: v/total for t, v in td.items()}
    nGames += 1

    for t, w in normed.items():
        tagTotalWeight[t] += w

    items = list(normed.items())
    for i in range(len(items)):
        for j in range(i+1, len(items)):
            a, wa = items[i]
            b, wb = items[j]
            if a > b:
                a, b = b, a
            coOcc[(a,b)] += wa*wb

print("pairs found:", str(len(coOcc)))
print("")


# NPMI - handles the "singleplayer appears everywhere" problem
# raw co-occurrence makes common tags look related to everything
npmiScores = {}

for (a, b), val in coOcc.items():
    if val < MIN_PAIR_FREQ:
        continue

    pA  = tagTotalWeight[a] / nGames
    pB  = tagTotalWeight[b] / nGames
    pAB = val / nGames

    if pA <= 0 or pB <= 0 or pAB <= 0:
        continue

    pmi  = np.log(pAB / (pA*pB))
    npmi = pmi / (-np.log(pAB))   # bounded -1 to 1

    if np.isnan(npmi) or np.isinf(npmi):
        continue

    npmiScores[(a, b)] = npmi

# negative npmi = tags that avoid each other, not useful for clustering
posNpmi = {pair: s for pair, s in npmiScores.items() if s > 0}
print("positive npmi pairs:", str(len(posNpmi)))
print("")


# heatmap of top tags - helps sanity check that npmi makes sense
topHeatTags = [t for t, _ in sorted(tagTotalWeight.items(), key=lambda x: x[1], reverse=True)[:TOP_TAGS_HEATMAP]]
heatMat = np.zeros((TOP_TAGS_HEATMAP, TOP_TAGS_HEATMAP))

for i in range(TOP_TAGS_HEATMAP):
    for j in range(TOP_TAGS_HEATMAP):
        if i == j:
            heatMat[i,j] = 1.0
            continue
        k = (min(topHeatTags[i], topHeatTags[j]), max(topHeatTags[i], topHeatTags[j]))
        heatMat[i,j] = npmiScores.get(k, 0)

fig, ax = plt.subplots(figsize=(18, 16))
sns.heatmap(heatMat, xticklabels=topHeatTags, yticklabels=topHeatTags,
            cmap="RdYlGn", center=0, square=True, linewidths=0.1, ax=ax)
ax.set_title("NPMI Heatmap - Top " + str(TOP_TAGS_HEATMAP) + " Tags")
plt.xticks(rotation=90, fontsize=7)
plt.yticks(rotation=0, fontsize=7)
plt.tight_layout()
plt.savefig("npmi_heatmap.png", dpi=150, bbox_inches="tight")
plt.show()


# build igraph - leidenalg only works with igraph objects, not networkx
netTagSet = set()
for (a, b) in posNpmi:
    netTagSet.add(a)
    netTagSet.add(b)

netTags    = sorted(list(netTagSet))
netIdx     = {tag: i for i, tag in enumerate(netTags)}

edges    = [(netIdx[a], netIdx[b]) for (a,b) in posNpmi]
eWeights = [float(s) for s in posNpmi.values()]

g = ig.Graph()
g.add_vertices(len(netTags))
g.vs["name"] = netTags
g.add_edges(edges)
g.es["weight"] = eWeights

print("network built -", str(g.vcount()), "nodes,", str(g.ecount()), "edges")
print("")

# run leiden multiple times to check stability
# if ARI is low then the partition is too unstable to trust
print("running Leiden " + str(N_LEIDEN_RUNS) + " times...")
memberships = []
for seed in range(N_LEIDEN_RUNS):
    part = la.find_partition(g, la.ModularityVertexPartition,
                              weights="weight", n_iterations=-1, seed=seed)
    memberships.append(list(part.membership))

ariVals = [round(adjusted_rand_score(memberships[0], memberships[i]), 4)
           for i in range(1, N_LEIDEN_RUNS)]
print("ARI scores:", ariVals)
print("mean ARI:", str(round(float(np.mean(ariVals)), 4)))
print("")

finalMembership = memberships[0]
tagCluster      = {netTags[i]: finalMembership[i] for i in range(len(netTags))}
nClusters       = max(finalMembership) + 1
print("clusters found:", str(nClusters))
print("")

# print top tags per cluster so we can name them
clusterContent = defaultdict(list)
for tag, cid in tagCluster.items():
    clusterContent[cid].append((tag, tagTotalWeight[tag]))

print("top 10 tags per cluster:")
for cid in sorted(clusterContent.keys()):
    top = sorted(clusterContent[cid], key=lambda x: x[1], reverse=True)[:10]
    print("  " + str(cid) + ": " + ", ".join(t[0] for t in top))

print("")
print("fill in clusterNames below then re-run from the network plot section")
print("")

# these cluster names are filled by me, they are pretty simplified imo
clusterNames = {
    0: "Action",
    1: "Simulation",
    2: "Indie",
    3: "Strategy",
    4: "2D Aesthetic",
    5: "Horror/Shooter",
    6: "RPG",
    7: "Visual Novel",
    8: "Comedy",
    9: "Utilities",
    10: "Illustration and Animation"
}


# network visualisation - coloured by cluster
# networkx has better matplotlib integration than igraph for this
G = nx.Graph()
for tag in netTags:
    G.add_node(tag, cluster=tagCluster[tag])
for (a, b), s in posNpmi.items():
    if a in netIdx and b in netIdx:
        G.add_edge(a, b, weight=s)

if len(G.nodes) > 300:
    keepSet = set(t for t, _ in sorted(tagTotalWeight.items(), key=lambda x: x[1], reverse=True)[:300])
    G = G.subgraph(keepSet).copy()

cmap  = cm.tab20(np.linspace(0, 1, max(nClusters, 1)))
nCol  = [cmap[tagCluster.get(n, 0) % nClusters] for n in G.nodes]
pos   = nx.spring_layout(G, weight="weight", k=0.6, seed=42)

fig, ax = plt.subplots(figsize=(18, 14))
nx.draw_networkx_nodes(G, pos, node_color=nCol, node_size=90, alpha=0.85, ax=ax)
nx.draw_networkx_edges(G, pos, alpha=0.15, edge_color="grey", ax=ax)
nx.draw_networkx_labels(G, pos, font_size=5, ax=ax)
ax.set_title("Steam Tag Network - Leiden Clusters")
ax.axis("off")
plt.tight_layout()
plt.savefig("tag_network.png", dpi=150, bbox_inches="tight")
plt.show()


# map games to clusters using same within-game weights
def gameClusterWeights(tagDict, tagCluster):
    total = sum(tagDict.values())
    if total == 0:
        return {}, []
    normed = {t: v/total for t, v in tagDict.items()}
    cw = defaultdict(float)
    for t, w in normed.items():
        if t in tagCluster:
            cw[tagCluster[t]] += w
    # also returns membership list directly, saves a separate pass
    members = [cid for cid, weight in cw.items() if weight >= MEMBERSHIP_THRESH]
    return dict(cw), members

cwList = []
cmList = []
for td in df["tagsParsed"]:
    cw, cm = gameClusterWeights(td, tagCluster)
    cwList.append(cw)
    cmList.append(cm)

df["clusterWeights"] = cwList
df["clusterMembers"] = cmList

print("avg clusters per game:", str(round(df["clusterMembers"].map(len).mean(), 2)))
print("")


# weighted avg score - weight by review count
# a game with 100 reviews matters 10x more than one with 10
def wAvg(subset):
    w = subset["totalReviewCount"]
    if w.sum() == 0:
        return np.nan
    return float((subset["review_score"] * w).sum() / w.sum())

singleRows = []
for cid in range(nClusters):
    mask = df["clusterMembers"].apply(lambda cm: cid in cm)
    sub  = df[mask]
    if len(sub) < 10:
        continue
    singleRows.append({
        "cluster": clusterNames[cid],
        "cid":     cid,
        "score":   round(wAvg(sub), 2),
        "games":   len(sub)
    })

singleDf = pd.DataFrame(singleRows).sort_values("score", ascending=False)
print("single cluster scores:")
print(singleDf.to_string(index=False))
print("")

comboRows = []
for c1, c2 in combinations(range(nClusters), 2):
    mask = df["clusterMembers"].apply(lambda cm: c1 in cm and c2 in cm)
    sub  = df[mask]
    if len(sub) < 50:
        continue
    comboRows.append({
        "cluster1": clusterNames[c1],
        "cluster2": clusterNames[c2],
        "score":    round(wAvg(sub), 2),
        "games":    len(sub)
    })

comboDf = pd.DataFrame(comboRows).sort_values("score", ascending=False)
print("top combos:")
print(comboDf.head(20).to_string(index=False))
print("")
print("worst combos:")
print(comboDf.tail(10).to_string(index=False))
print("")

singleDf.to_csv("single_cluster_scores.csv", index=False)
comboDf.to_csv("combo_scores.csv", index=False)


# bar chart single cluster scores
med   = singleDf["score"].median()
bCols = ["#2ecc71" if s >= med else "#e74c3c" for s in singleDf["score"]]

fig, ax = plt.subplots(figsize=(12, max(5, len(singleDf) * 0.4)))
ax.barh(singleDf["cluster"], singleDf["score"], color=bCols)
ax.axvline(med, color="black", linestyle="--", alpha=0.5, label="median")
ax.set_xlabel("Weighted Avg Review Score")
ax.set_title("Review Score by Genre Cluster")
ax.legend()
plt.tight_layout()
plt.savefig("cluster_scores_bar.png", dpi=150, bbox_inches="tight")
plt.show()

# heatmap of cluster combo scores
allNames = [clusterNames[i] for i in range(nClusters)]
heatDf   = pd.DataFrame(np.nan, index=allNames, columns=allNames)

for _, r in singleDf.iterrows():
    n = r["cluster"]
    if n in heatDf.index:
        heatDf.loc[n, n] = r["score"]

for _, r in comboDf.iterrows():
    n1, n2 = r["cluster1"], r["cluster2"]
    if n1 in heatDf.index and n2 in heatDf.columns:
        heatDf.loc[n1, n2] = r["score"]
        heatDf.loc[n2, n1] = r["score"]

allVals = heatDf.stack().dropna()
vMid    = allVals.median() if len(allVals) > 0 else 70

fig, ax = plt.subplots(figsize=(14, 12))
sns.heatmap(heatDf, annot=True, fmt=".3f", cmap="RdYlGn",
            center=vMid, linewidths=0.5, square=True, ax=ax)
ax.set_title("Weighted Avg Review Score - Cluster Combinations")
plt.xticks(rotation=45, ha="right", fontsize=8)
plt.yticks(rotation=0, fontsize=8)
plt.tight_layout()
plt.savefig("cluster_combo_heatmap.png", dpi=150, bbox_inches="tight")
plt.show()

# boxplot - score spread per cluster
longRows = []
for _, row in df.iterrows():
    for cid in row["clusterMembers"]:
        longRows.append({
            "cluster":     clusterNames.get(cid, "C" + str(cid)),
            "reviewScore": row["review_score"]
        })

longDf = pd.DataFrame(longRows)
cOrder = longDf.groupby("cluster")["reviewScore"].median().sort_values(ascending=False).index.tolist()

# kruskal-wallis - tests if any cluster differs significantly
# non-parametric, doesnt assume normality which is right for review scores
clusterGroups     = [g["reviewScore"].values for _, g in longDf.groupby("cluster")]
clusterGroupNames = [n for n, _ in longDf.groupby("cluster")]

kwStat, kwP = stats.kruskal(*clusterGroups)
print("Kruskal-Wallis H =", str(round(kwStat, 4)), "  p =", str(kwP))
print("")

if kwP < 0.05:
    print("significant - running Dunn post-hoc (Bonferroni correction)...")
    print("")
    dunnResult = sp.posthoc_dunn(longDf, val_col="reviewScore", group_col="cluster", p_adjust="bonferroni")
    print(dunnResult.round(4).to_string())
    print("")
    dunnResult.round(4).to_csv("dunn_posthoc.csv")
    print("saved: dunn_posthoc.csv")
else:
    print("not significant at p < 0.05 - no post-hoc needed")
print("")

fig, ax = plt.subplots(figsize=(14, 7))
sns.boxplot(data=longDf, x="cluster", y="reviewScore",
            order=cOrder, palette="RdYlGn_r", ax=ax)
ax.set_title("Review Score Distribution by Genre Cluster")
ax.set_xlabel("Genre Cluster")
ax.set_ylabel("Review Score")
plt.xticks(rotation=45, ha="right")
plt.tight_layout()
plt.savefig("cluster_score_boxplot.png", dpi=150, bbox_inches="tight")
plt.show()

print("done")












