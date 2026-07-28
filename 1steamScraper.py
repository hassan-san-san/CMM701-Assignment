import requests
import time
import json
import csv
import os

steamSpyBase = "https://steamspy.com/api.php"
steamStoreBase = "https://store.steampowered.com/api/appdetails"
outputDir = "output"
minReviews =10

os.makedirs(outputDir, exist_ok=True)


# grabs all pages from steamspy
def pullSteamSpy():
    print("pulling all games from steamspy...")
    games = []

    for p in range(0, 45):
        print("page " + str(p) + "...")
        url = steamSpyBase + "?request=all&page=" + str(p)

        try:
            resp = requests.get(url, timeout=30)
            data = resp.json()

            if not data:
                print("empty page, probably done")
                break

            for appid,info in data.items():
                games.append(info)

        except Exception as e:
            print("page " + str(p) + " failed: " + str(e))

        # 1 req per 60 sec for bulk endpoint
        if p < 44:
            print("waiting 60s...")
            time.sleep(60)

    print("got " + str(len(games)) + " raw entries")
    return games


# kill the shovelware
def filterGames(games):
    filtered =[]
    for g in games:
        pos = g.get("positive",0) or 0
        neg = g.get("negative",0) or 0
        total = pos+neg

        if total<minReviews:
            continue

        if not g.get("name"):
            continue

        filtered.append(g)

    print("filtered to " + str(len(filtered)) + " games (min " + str(minReviews) + " reviews)")
    return filtered


# save so we dont lose it
def saveSteamSpyData(games):
    path = os.path.join(outputDir, "steamspy_raw.json")
    with open(path, "w") as f:
        json.dump(games, f, indent=2)
    print("saved steamspy data to " + path)



# this is the slow bit lol
def pullSteamStore(games):
    results = []
    total= len(games)
    failed = []

    # resume support
    progressPath = os.path.join(outputDir, "steam_store_progress.json")
    alreadyDone ={}
    if os.path.exists(progressPath):
        with open(progressPath, "r") as f:
            existing = json.load(f)
            for item in existing:
                alreadyDone[item["steam_appid"]] =item
            results = existing
        print("resuming... already have " + str(len(alreadyDone)) + " games")

    for i,game in enumerate(games):
        appid = str(game.get("appid", ""))

        if int(appid) in alreadyDone:
            continue

        if (i+1)%100 ==0 or i==0:
            print("steam store: " + str(i+1) + "/" + str(total) + "...")

        try:
            # force english store page
            url = steamStoreBase + "?appids=" +appid + "&l=english"
            resp = requests.get(url, timeout=15)
            data = resp.json()

            appData = data.get(appid, {})
            if not appData.get("success"):
                failed.append(appid)
                time.sleep(2)
                continue

            d = appData["data"]

            # big dict but whatever
            entry = {
                "steam_appid": int(appid),
                "name": d.get("name", ""),
                "type": d.get("type", ""),
                "required_age": d.get("required_age", 0),
                "is_free": d.get("is_free", False),
                "developers": ", ".join(d.get("developers", [])),
                "publishers": ", ".join(d.get("publishers", [])),
                "price_usd": d.get("price_overview", {}).get("final", 0) /100 if d.get("price_overview") else 0,
                "initial_price_usd": d.get("price_overview", {}).get("initial", 0)/100 if d.get("price_overview") else 0,
                "discount_pct": d.get("price_overview", {}).get("discount_percent", 0) if d.get("price_overview") else 0,
                "windows": d.get("platforms", {}).get("windows", False),
                "mac": d.get("platforms", {}).get("mac", False),
                "linux": d.get("platforms", {}).get("linux", False),
                "platform_count": sum([
                    d.get("platforms", {}).get("windows", False),
                    d.get("platforms", {}).get("mac", False),
                    d.get("platforms", {}).get("linux", False)
                ]),
                "achievement_count": d.get("achievements", {}).get("total", 0) if d.get("achievements") else 0,
                "dlc_count": len(d.get("dlc", [])),
                "screenshot_count": len(d.get("screenshots", [])),
                "trailer_count": len(d.get("movies", [])),
                "has_trailer": len(d.get("movies", [])) > 0,
                "metacritic_score": d.get("metacritic", {}).get("score", None) if d.get("metacritic") else None,
                "total_reviews": d.get("recommendations", {}).get("total", 0) if d.get("recommendations") else 0,
                "controller_support": d.get("controller_support", "none"),
                "short_description": d.get("short_description", ""),
                "description_length": len(d.get("detailed_description", "")),
                "genres": ", ".join([g["description"] for g in d.get("genres", [])]),
                "categories": ", ".join([c["description"] for c in d.get("categories", [])]),
                "supported_languages": d.get("supported_languages", ""),
                "language_count": d.get("supported_languages", "").count(",") + 1 if d.get("supported_languages") else 0,
                "release_date": d.get("release_date", {}).get("date", ""),
                "coming_soon": d.get("release_date", {}).get("coming_soon", False),
            }

            results.append(entry)

        except Exception as e:
            print("failed on " +appid+ ": " + str(e))
            failed.append(appid)

        # checkpoint every 50
        if len(results)%50==0 and len(results)>0:
            with open(progressPath, "w") as f:
                json.dump(results, f)

        # dont get rate limited
        time.sleep(2)

    with open(progressPath, "w") as f:
        json.dump(results, f)

    print("")
    print("pulled " + str(len(results)) + " games from steam store")
    print("failed: " + str(len(failed)))
    return results, failed


# grabs tags per game from steamspy appdetails
# the bulk endpoint doesnt give us these smh
def pullSteamSpyTags(games):
    tagData ={}
    total = len(games)
    failed = []

    # resume support
    progressPath = os.path.join(outputDir, "steamspy_tags_progress.json")
    if os.path.exists(progressPath):
        with open(progressPath, "r") as f:
            tagData = json.load(f)
        print("resuming tags... already have " + str(len(tagData)))

    for i,game in enumerate(games):
        appid = str(game.get("appid", ""))

        if appid in tagData:
            continue

        if (i+1)%100 ==0 or i==0:
            print("steamspy tags: " + str(i+1) + "/" + str(total) + "...")

        try:
            url = steamSpyBase + "?request=appdetails&appid=" +appid
            resp = requests.get(url, timeout=15)
            d = resp.json()

            tags = d.get("tags", {})
            if isinstance(tags, dict):
                tagData[appid] = tags
            else:
                tagData[appid] ={}

        except Exception as e:
            print("tag pull failed on " +appid+ ": " + str(e))
            failed.append(appid)
            tagData[appid] ={}

        # checkpoint every 100
        if len(tagData)%100==0 and len(tagData)>0:
            with open(progressPath, "w") as f:
                json.dump(tagData, f)

        # 1 req per sec
        time.sleep(1)

    with open(progressPath, "w") as f:
        json.dump(tagData, f)

    print("")
    print("pulled tags for " + str(len(tagData)) + " games")
    print("failed: " + str(len(failed)))
    return tagData


# stitch it all together
def mergeData(steamSpyGames, steamStoreGames, tagData):
    spyLookup ={}
    for g in steamSpyGames:
        spyLookup[g.get("appid")] =g

    merged = []
    for store in steamStoreGames:
        appid =store["steam_appid"]
        spy = spyLookup.get(appid, {})

        # engagement stuff from steamspy
        store["owners"] = spy.get("owners", "")
        store["ccu"] = spy.get("ccu", 0)
        store["avg_playtime_forever"] = spy.get("average_forever", 0)
        store["median_playtime_forever"] = spy.get("median_forever", 0)
        store["avg_playtime_2weeks"] = spy.get("average_2weeks", 0)
        store["median_playtime_2weeks"] = spy.get("median_2weeks", 0)
        store["positive_reviews"] = spy.get("positive", 0)
        store["negative_reviews"] = spy.get("negative", 0)
        store["score_rank"] = spy.get("score_rank", "")

        # tags from per-game pull
        gameTags = tagData.get(str(appid), {})
        store["tags"] = json.dumps(gameTags) if gameTags else "{}"

        # review ratio
        pos = store["positive_reviews"] or 0
        neg =store["negative_reviews"] or 0
        store["review_score"] = round(pos/(pos +neg), 4) if (pos +neg)>0 else None

        merged.append(store)

    print("merged " + str(len(merged)) + " games")
    return merged


def saveCSV(merged):
    if not merged:
        print("nothing to save lol")
        return

    path = os.path.join(outputDir, "steam_dataset.csv")
    keys = merged[0].keys()

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(merged)

    print("saved to " + path)
    print("columns: " + str(len(keys)))
    print("rows: " + str(len(merged)))



if __name__ == "__main__":
    # step 1 - steamspy bulk
    spyGames = pullSteamSpy()
    saveSteamSpyData(spyGames)

    # step 2 - filter
    filtered = filterGames(spyGames)

    # step 3 - steam store metadata
    storeGames, failedIds = pullSteamStore(filtered)

    # step 4 - steamspy per-game tags
    tagData = pullSteamSpyTags(filtered)

    # step 5 - merge all three
    merged = mergeData(filtered, storeGames, tagData)

    # step 6 - done
    saveCSV(merged)

    print("")
    print("done. check output/steam_dataset.csv")
    if failedIds:
        print("failed ids: " + str(len(failedIds)))















