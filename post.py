import sys
import re
import configparser
import requests
import pathlib
import frontmatter
import markdown
from bs4 import BeautifulSoup
from PIL import Image
import io

INI = configparser.ConfigParser()
INI.read("./config.ini")

# 画像リンクカスタマイズ
RE_REMOTEIMG = re.compile("^(http|https):.+")


def get_item(label: str, params: dict, raise_exception=True):
    """
    アイテムの情報を取得する。
    """
    # リクエスト
    res = requests.get(
        f'{INI["url"]["api"]}/{label}',
        params=params,
        auth=(INI["auth"]["user"], INI["auth"]["pass"]),
    )

    # HTTPレスポンスチェック
    if not res.ok:
        raise Exception(f"HTTPエラー status_code={res.status_code}")

    # OKであれば、結果のJSONを取り出し
    items = res.json()

    # アイテムのリストが１件じゃなければエラー、１件ならそれを返す
    if len(items) != 1:
        if raise_exception:
            raise Exception(f"アイテムが見つからない label={label} params={params}")
        else:
            return None
    else:
        return items[0]


def upload_image(img_local_path: pathlib.Path, img_blog_path: pathlib.Path):
    """
    画像をアップロードして、新しくできたアイテム情報を返す。
    アップロード済みなら、そのアイテムの情報を返す。
    """
    # アップロード済みであれば、その情報を返す
    item = get_item("media", dict(slug=img_blog_path.stem), False)
    if item:
        return item

    # 画像のバイナリを取得
    im = Image.open(img_local_path)
    if im.width > int(INI["img"]["max_size"]):
        resize_r = int(INI["img"]["max_size"]) / im.width
        im = im.resize((int(im.width * resize_r), int(im.height * resize_r)))
    im = im.convert("RGB")
    output = io.BytesIO()
    im.save(output, format="JPEG")
    imagebin = output.getvalue()

    # ポストするヘッダを作成
    headers = {
        "Content-Type": get_media_type(INI["img"]["ext"]),
        "Content-Disposition": f"attachment; filename={img_blog_path.stem}.{INI['img']['ext']}",
    }

    # POST
    res = requests.post(
        f'{INI["url"]["api"]}/media',
        headers=headers,
        data=imagebin,
        auth=(INI["auth"]["user"], INI["auth"]["pass"]),
    )

    if not res.ok:
        raise Exception(f"HTTPエラー status_code={res.status_code}")
    return res.json()


def get_media_type(ext: str) -> str:
    if ext == "jpg":
        return "image/jpg"
    elif ext == "png":
        return "image/png"
    return ""


def post(md_path: pathlib.Path):
    # Markdownファイル読み込み
    with open(md_path, "r") as f:
        md_file = frontmatter.load(f)

    # メタデータ
    meta = md_file.metadata

    # POSTするデータ
    postdata = dict()

    # 記事のスラッグをファイル名から作成
    postdata["slug"] = md_path.stem

    # metaからpostdataを作成
    for key, value in meta.items():
        if key == "categories" or key == "tags":
            postdata[key] = [get_item(key, dict(slug=x))["id"] for x in meta[key]]
        else:
            postdata[key] = value

    # 記事本文をHTMLに変換
    # md = markdown.Markdown(extensions=EXTENSIONS)
    md = markdown.Markdown(extensions=["fenced_code", "tables"])
    postdata["content"] = md.convert(md_file.content)

    # アイキャッチ（featured media）のアップロードと設定
    img_local_path = md_path.parent.joinpath(f"{md_path.stem}.{INI['fm']['ext']}")
    if img_local_path.is_file():

        # アイキャッチが作成してあれば、それを使う
        # アイキャッチの画像は"fm-"＋記事のスラッグ
        img_blog_slug = f"fm-{postdata['slug']}"
        img_blog_path = md_path.parent.joinpath(f"fm-{postdata['slug']}{img_local_path.suffix}")
        postdata["featured_media"] = upload_image(img_local_path, img_blog_path)["id"]

    else:

        # 未作成であればデフォルトのIDを使う
        postdata["featured_media"] = int(INI["fm"]["id_none"])

    # 記事本文のHTMLを処理していくのでHTMLをパース
    content_nd = BeautifulSoup(postdata["content"], features="html.parser")

    # 本文の画像リンクの画像をアップロードしてパスを変更
    for img_nd in content_nd.select("img"):

        # htmlのimgのsrc属性
        relative_path = img_nd.attrs["src"]

        # src属性がなければ無視（あるはずだけど）
        if not relative_path:
            continue

        # src属性が外部リンクであれば無視
        if RE_REMOTEIMG.match(relative_path):
            continue

        # ローカルの画像ファイルパス
        img_local_path = md_path.parent.joinpath(relative_path)

        # アップロードするときのスラッグ（記事のスラッグ＋"_"＋元の画像ファイル名）
        img_blog_slug = f"{postdata['slug']}_{img_local_path.stem}"
        img_blog_path = md_path.parent.joinpath(f"{img_blog_slug}{img_local_path.suffix}")

        # アップロードしてsrc属性を変更する
        img_item = upload_image(img_local_path, img_blog_path)
        src_url = img_item["source_url"].replace(INI["url"]["site"], "")
        img_nd.attrs["src"] = src_url

        # クリッカブルに変更する
        atag = content_nd.new_tag("a", href=src_url)
        img_nd.replace_with(atag)
        atag.append(img_nd)

    # 結果を戻す
    postdata["content"] = str(content_nd)

    # 記事を投稿
    item = get_item("posts", dict(slug=postdata["slug"], status="publish,draft"), False)
    if item:
        url = f"{INI['url']['api']}/posts/{item['id']}"
    else:
        url = f"{INI['url']['api']}/posts"
    res = requests.post(
        url,
        json=postdata,
        auth=(INI["auth"]["user"], INI["auth"]["pass"]),
    )
    if not res.ok:
        raise Exception(f"HTTPエラー status_code={res.status_code}")
    print(f"投稿完了 id={res.json()['id']}")


if __name__ == "__main__":
    md_path = pathlib.Path(sys.argv[1])
    # md_path = pathlib.Path("/home/takada/work/masa86blog/01_vscode/01-blog/vscode-blog.md")
    post(md_path.absolute())
