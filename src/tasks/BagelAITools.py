import base64
import json
import random
import re
import cv2
import requests

from ok import TaskDisabledException, og
from qfluentwidgets import FluentIcon

from src.tasks.BaseNTETask import BaseNTETask
from src.tasks.NTEOneTimeTask import NTEOneTimeTask

def get_app_locale() -> bool:
    """get app locale."""

    try:
        return og.app.locale.name()
    except Exception:
        return None

class BagelAITools(NTEOneTimeTask, BaseNTETask):
    # ==========================================
    # 配置区域
    # ==========================================

    CONF_GAME_LANG = "游戏语言"
    CONF_MODEL = "调用模型"
    CONF_HELPER_MODE = "文案助手模式"
    CONF_AUTO_AICONFIG = "智能体模式选项"
    CONF_MODEL_URL = "模型调用地址"
    CONF_MODEL_API = "模型调用API_Key"
    CONF_MODEL_NAME = "所调用模型名称"
    CONF_PROMPT_REPLY = "回复模块提示词"
    CONF_PROMPT_POST_TITLE = "发帖标题模块提示词"
    CONF_PROMPT_POST_CONTENT = "发帖内容模块提示词"
    INFO_HELPER_COUNT = "帮助文案生成次数"
    INFO_LIKE_COUNT = "成功按赞次数"
    BASE_BAGEL_I18N ={
        "bagel_ocr":{
            "zh_CN":{
                "bagel_icon": "呗果",
                "sort_menu_area": "推荐|总热门|最新|今日|本周|关注",
                "sort_menu_select": "最新",
                "reply_area": "说点什么",
                "post_text": "发布",
                "post_check_area": "发布帖子",
                "post_photo_zone_area": "请选择发布内容",
                "confirm": "确认",
                "post_title_area": "请输入标题",
                "post_content_area": "请输入正文",
            },
            "zh_TW":{
                "bagel_icon": "唄果",
                "sort_menu_area": "推薦|總熱門|最新|今日|本週|關注",
                "sort_menu_select": "最新",
                "reply_area": "說點什麼",
                "post_text": "發佈",
                "post_check_area": "發佈貼文",
                "post_photo_zone_area": "請選擇發佈內容",
                "confirm": "確認",
                "post_title_area": "請輸入標題",
                "post_content_area": "請輸入正文",
            },
            "ja_JP": {
                "bagel_icon": "ベーグル",
                "sort_menu_area": "おすすめ|総合|新着|今日|今週|フォロー",
                "sort_menu_select": "新着",
                "reply_area": "コメントする",
                "post_text": "投稿",
                "post_check_area": "投稿する",
                "post_photo_zone_area": "投稿内容を選択",
                "confirm": "確定",
                "post_title_area": "を入",
                "post_content_area": "本文を入",
            },
            "ko_KR": {
                "bagel_icon": "베이글",
                "sort_menu_area": "추천|전체|최신|오늘의|이번|팔로우",
                "sort_menu_select": "최신",
                "reply_area": "이야기를", # 이야기를 들려주세요
                "post_text": "게시",
                "post_check_area": "게시물", # 게시물 게시
                "post_photo_zone_area": "내용을", # 게시할 내용을 선택해 주세요
                "confirm": "확인",
                "post_title_area": "제목을",
                "post_content_area": "본문을",
            },
            "en_US": {
                "bagel_icon": "Bagel",
                "sort_menu_area": "Recommended|Top|Latest|Daily|Weekly|Following",
                "sort_menu_select": "Latest",
                "reply_area": "Say", # Say something
                "post_text": "Post",
                "post_check_area": "Post",
                "post_photo_zone_area": "Select", # Select content to post
                "confirm": "Confirm",
                "post_title_area": "subject", # Enter a subject
                "post_content_area": "main", # Enter your main text
            },
            "es_ES": {
                "bagel_icon": "Bagel",
                "sort_menu_area": "Recomendadas|principales|recientes|Favoritos|semana|Siguiendo",
                "sort_menu_select": "recientes",
                "reply_area": "algo", # Di algo
                "post_text": "Publicar",
                "post_check_area": "Publicar",
                "post_photo_zone_area": "Selecciona", # Selecciona contenido para publicar
                "confirm": "Confirmar",
                "post_title_area": "asunto", # Ingresa un asunto
                "post_content_area": "texto", # Ingresa el texto principal
            },
            "pt_BR": {
                "bagel_icon": "Bagel",
                "sort_menu_area": "Recomendadas|principales|recientes|Favoritos|semana|Siguiendo",
                "sort_menu_select": "recientes",
                "reply_area": "algo", # Di algo
                "post_text": "Publicar",
                "post_check_area": "Publicar",
                "post_photo_zone_area": "Selecciona", # Selecciona contenido para publicar
                "confirm": "Confirmar",
                "post_title_area": "asunto", # Ingresa un asunto
                "post_content_area": "texto", # Ingresa el texto principal
            },
            "de_DE": {
                "bagel_icon": "Bagel",
                "sort_menu_area": "Empfohlen|Top|Neuestes|des|Wochen|Folgt",
                "sort_menu_select": "Neuestes",
                "reply_area": "etwas", # Sag etwas
                "post_text": "Posten",
                "post_check_area": "Posten",
                "post_photo_zone_area": "nhalt", #
                "confirm": "tigen", # bestätigen
                "post_title_area": "eingeben", # Betreff eingeben
                "post_content_area": "deinen", # Gib deinen Haupttext ein
            },
            "fr_FR":{
                "bagel_icon": "Bagel",
                "sort_menu_area": "Recommand|populaires|cent|jour|semaine|Abonnements",
                "sort_menu_select": "cent",
                "reply_area": "quelque", # Écrivez quelque chose
                "post_text": "Publication",
                "post_check_area": "Publication",
                "post_photo_zone_area": "lectionnez", # Sélectionnez le contenu à publier
                "confirm": "Confirmer",
                "post_title_area": "objet", # Saisir un objet
                "post_content_area": "Saisissez", # Saisissez le corps de texte
            },
            "ru_RU":{
                "bagel_icon": "Bagel",
                "sort_menu_area": "PekoMeHAaun|TpeHAe|Новое|Ton|HeAenn|OANNCKN",
                "sort_menu_select": "Новое",
                "reply_area": "HannwnTe", # Напишите что-нибудь
                "post_text": "Ony6nnKoBaTb",
                "post_check_area": "Ony6nnKoBaTb",
                "post_photo_zone_area": "Bbi6epute", # Выберите контент для публикации
                "confirm": "noATBepAnTb",
                "post_title_area": "BBeante", # Введите тему
                "post_content_area": "BBeante", # Введите текст публикации
            },
        },
        "model_prompt":{
            "zh_CN": {
                "REPLY": "帮我写一段回复文案，\n直接回复文案本身，\n不要包含任何其他解释性文本，\n语言风格贴合帖子内容，\n可以的情况下俏皮一些\n回复内容不超过25字符。",
                "POST_TITLE": "这是帖子配图，\n帮我写一段发帖用标题，\n直接回复标题本身，\n不要包含任何其他解释性文本，\n语言风格贴合配图内容，\n可以的情况下俏皮一些\n标题内容不超过20字符。",
                "POST_CONTENT": "帮我写一段发帖用文案，\n直接回复文案本身，\n不要包含任何其他解释性文本，\n语言风格贴合配图内容，\n可以的情况下俏皮一些\n文案内容不超过50字符。"
            },
            "zh_TW": {
                "REPLY": "幫我寫一段回覆文案，\n直接回覆文案本身，\n不要包含任何其他解釋性文本，\n語言風格貼合貼文內容，\n可以的情況下俏皮一些\n回覆內容不超過25字元。",
                "POST_TITLE": "這是貼文配圖，\n幫我寫一段發文用標題，\n直接回覆標題本身，\n不要包含任何其他解釋性文本，\n語言風格貼合配圖內容，\n可以的情況下俏皮一些\n標題內容不超過20字元。",
                "POST_CONTENT": "幫我寫一段發文用文案，\n直接回覆文案本身，\n不要包含任何其他解釋性文本，\n語言風格貼合配圖內容，\n可以的情況下俏皮一些\n文案內容不超過50字元。"
            },
            "ja_JP": {
                "REPLY": "この投稿への返信コメントを1点作成してください。\n前置きや解説などの余計なテキストは一切含めず、\nコメント本文のみを直接出力してください。\n投稿内容に合わせたトーンで、\n可能であれば少しユーモアのある表現にしてください。\n文字数は25文字以内とします。",
                "POST_TITLE": "これは投稿の添付画像です。\nこの投稿用のタイトルを作成してください。\n前置きや解説などの余計なテキストは一切含めず、\nタイトル本文のみを直接出力してください。\n画像内容に合わせたトーンで、\n可能であれば少しユーモアのある表現にしてください。\n文字数は20文字以内とします。",
                "POST_CONTENT": "この投稿用のキャプション文を作成してください。\n前置きや解説などの余計なテキストは一切含めず、\n本文のみを直接出力してください。\n画像内容に合わせたトーンで、\n可能であれば少しユーモアのある表現にしてください。\n文字数は50文字以内とします。"
            },
            "ko_KR": {
                "REPLY": "이 게시물에 달 시 댓글 문구를 작성해 주세요.\n서론이나 설명 등 불필요한 텍스트는 일체 포함하지 말고, 댓글 본문만 직접 출력해 주세요.\n게시물 내용과 어울리는 톤으로, 가능하면 약간 위트 있게 작성해 주세요.\n공백 포함 25자 이내로 제한합니다.",
                "POST_TITLE": "게시물에 첨부된 이미지입니다.\n이 게시물에 사용할 제목을 작성해 주세요.\n서론이나 설명 등 불필요한 텍스트는 일체 포함하지 말고, 제목만 직접 출력해 주세요.\n이미지 내용과 어울리는 톤으로, 가능하면 약간 위트 있게 작성해 주세요.\n공백 포함 20자 이내로 제한합니다.",
                "POST_CONTENT": "이 게시물에 사용할 본문 문구를 작성해 주세요.\n서론이나 설명 등 불필요한 텍스트는 일체 포함하지 말고, 본문만 직접 출력해 주세요.\n이미지 내용과 어울리는 톤으로, 가능하면 약간 위트 있게 작성해 주세요.\n공백 포함 50자 이내로 제한합니다."
            },
            "en_US": {
                "REPLY": "Write a reply comment for this post.\nRespond ONLY with the comment text itself.\nDo NOT include any introduction, explanation, or conversational filler.\nStyle should match the post content, slightly playful if possible.\nMaximum length: 50 characters.",
                "POST_TITLE": "This is the image for a new post.\nWrite a title for this post.\nRespond ONLY with the title text itself.\nDo NOT include any introduction, explanation, or conversational filler.\nStyle should match the image, slightly playful if possible.\nMaximum length: 40 characters.",
                "POST_CONTENT": "Write a body text for this post.\nRespond ONLY with the text itself.\nDo NOT include any introduction, explanation, or conversational filler.\nStyle should match the image, slightly playful if possible.\nMaximum length: 100 characters."
            },
            "es_ES": {
                "REPLY": "Escribe un comentario de respuesta para esta publicación.\nResponde ÚNICAMENTE con el texto del comentario.\nNo incluyas introducciones, explicaciones ni texto adicional.\nEl estilo debe adaptarse al contenido del post, preferiblemente un poco ingenioso.\nMáximo 50 caracteres.",
                "POST_TITLE": "Esta es la imagen de una nueva publicación.\nEscribe un título para esta publicación.\nResponde ÚNICAMENTE con el texto del título.\nNo incluyas introducciones, explicaciones ni texto adicional.\nEl estilo debe adaptarse a la imagen, preferiblemente un poco ingenioso.\nMáximo 40 caracteres.",
                "POST_CONTENT": "Escribe el texto principal (pie de foto) para esta publicación.\nResponde ÚNICAMENTE con el texto de la publicación.\nNo incluyas introducciones, explicaciones ni texto adicional.\nEl estilo debe adaptarse a la imagen, preferiblemente un poco ingenioso.\nMáximo 100 caracteres."
            },
            "pt_BR": {
                "REPLY": "Escreva um comentário de resposta para esta postagem.\nResponda APENAS com o texto do comentário em si.\nNão inclua introduções, explicações ou qualquer texto adicional.\nO estilo deve combinar com o conteúdo do post, se possível um pouco descontraído.\nMáximo de 50 caracteres.",
                "POST_TITLE": "Esta é a imagem de uma nova postagem.\nEscreva um título para esta postagem.\nResponda APENAS com o texto do título em si.\nNão inclua introduções, explicações ou qualquer texto adicional.\nO estilo deve combinar com a imagem, se possível um pouco descontraído.\nMáximo de 40 caracteres.",
                "POST_CONTENT": "Escreva o texto principal para esta postagem.\nResponda APENAS com o texto da postagem em si.\nNão inclua introduções, explicações ou qualquer texto adicional.\nO estilo deve combinar com a imagem, se possível um pouco descontraído.\nMáximo de 100 caracteres."
            },
            "de_DE": {
                "REPLY": "Schreibe eine kurze, charmante Antwort auf diesen Beitrag.\nAntworte direkt ohne Erklärungen.\nDer Stil sollte passend und gerne humorvoll sein.\nMaximal 50 Zeichen.",
                "POST_TITLE": "Dies ist ein Bild für einen Beitrag.\nSchreibe einen kurzen, charmanten Titel.\nAntworte direkt ohne Erklärungen.\nDer Stil sollte zum Bild passen und gerne humorvoll sein.\nMaximal 40 Zeichen.",
                "POST_CONTENT": "Schreibe einen kurzen, charmanten Text für diesen Beitrag.\nAntworte direkt ohne Erklärungen.\nDer Stil sollte zum Bild passen und gerne humorvoll sein.\nMaximal 100 Zeichen."
            },
            "fr_FR": {
                "REPLY": "Écris une réponse courte et charmante à ce post.\nRéponds directement sans explications.\nLe ton doit être adapté et idéalement plein d'esprit.\nMaximum 50 caractères.",
                "POST_TITLE": "Voici une image pour un post.\nÉcris un titre court et charmant.\nRéponds directement sans explications.\nLe ton doit correspondre à l'image et être plein d'esprit.\nMaximum 40 caractères.",
                "POST_CONTENT": "Écris un texte court et charmant pour ce post.\nRéponds directement sans explications.\nLe ton doit correspondre à l'image et être plein d'esprit.\nMaximum 100 caractères."
            },
            "ru_RU": {
                "REPLY": "Напиши короткий, остроумный ответ на этот пост.\nОтвечай только текстом ответа, без лишних слов.\nСтиль должен быть уместным и забавным.\nНе более 50 символов.",
                "POST_TITLE": "Это изображение для поста.\nПридумай короткий, остроумный заголовок.\nОтвечай только текстом, без лишних слов.\nСтиль должен соответствовать изображению и быть забавным.\nНе более 40 символов.",
                "POST_CONTENT": "Напиши короткий, остроумный текст для этого поста.\nОтвечай только текстом, без лишних слов.\nСтиль должен соответствовать изображению и быть забавным.\nНе более 100 символов."
            },
        },
        "preset_replies":{
            "zh_CN":[
                "非常好的帖子，使我疯狂点赞！",
                "前排围观，给大佬递茶~",
                "火钳刘明，这贴必火！",
                "拍的太好了，强烈支持一波！",
                "好耶、捕获一只宝藏！",
                "太强了，果断收藏点赞三连走起。",
                "这一贴尊嘟太美丽啦！",
                "谁懂，一打开呗果就被美图暴击！",
                "呜呜捕捉到宝藏帖子，果断点赞！",
                "纯路人，但在呗果刷到这个，直接留下回复！",
                "大家快来看，这贴拍的很好！",
                "这拍照技巧我实名羡慕。",
                "天哪这个构图！请狠狠把教程砸向我！",
                "这角色这衣服和场景绝配，种草了！",
                "又是被别人家画质惊艳到的一天。",
                "这个地方在哪呀？好美，我也得去打个卡！",
                "每一张都好看得可以直出当壁纸的程度，爱了爱了。",
                "这光影绝了！是不是偷偷开了什么高级滤镜？",
                "被治愈到了！",
                "多发点爱看！",
                "今天的呗果冲浪体验，因这篇帖子而变得极好~",
                "继续加油高产！",
                "呗主主页还有其他好看的吗？",
                "今日份的美图已被我成功吸收！",
                "忍不住点进来看了好久，支持！",
                "前排围观，大佬吃得太好了吧！",
                "我一直在刷帖，直到我看到了这篇（手动滑稽）",
                "火钳刘明！直觉告诉我这篇在呗果要爆！",
                "满分一百的话，呗主我给101分！",
                "太真实了。",
            ],
            "zh_TW": [
                "超讚的貼文，直接瘋狂點讚！",
                "前排卡位，給大佬遞茶～",
                "先卡一個，這篇必火！",
                "拍得太好了吧，強力支持一波！",
                "好耶！捕獲一隻寶藏創作者！",
                "太強了，果斷收藏點讚三連走起。",
                "這一篇真的太漂亮了吧！",
                "救命，一打開就被美圖暴擊！",
                "嗚嗚抓到寶藏貼文，果斷點讚！",
                "純路人，但刷到這個忍不住回覆！",
                "大家快來看，這篇拍得超好！",
                "這拍照技巧我實名羨慕了。",
                "天啊這個構圖！求教學砸向我！",
                "這角色衣服跟場景根本絕配，種草了",
                "又是被別人家畫質驚豔到的一天。",
                "這個地方在哪裡呀？超美我也要去！",
                "每張都好看得可以直接當桌布，愛了",
                "這光影絕了！是不是偷偷開了濾鏡？",
                "被治癒到了！",
                "多發點，超愛看！",
                "今天的衝浪體驗，因這貼文變超好～",
                "繼續加油，期待高產！",
                "原PO主頁還有其他好看的嗎？",
                "今日份的美圖已被我成功吸收！",
                "忍不住點進來看超久，支持！",
                "前排圍觀，大佬吃得太好了吧！",
                "刷到這篇，我直接停住了",
                "先卡位！直覺告訴我這篇會爆！",
                "滿分一百的話，原PO我給101分！",
                "太真實了。"
            ],
            "ja_JP": [
                "最高すぎる投稿！いいね連打したい！",
                "神投稿を前にして、まずはお茶をどうぞ",
                "これはバズる予感しかしない！カツ入れ",
                "撮影センス最高すぎます！全力で推せる",
                "最高かよ…！また一つ宝物を見つけた！",
                "強すぎる！速攻いいねと保存のコンボ！",
                "今回の投稿、尊すぎて尊死しそう…！",
                "助けて、美図の暴力で語彙力失った！",
                "うう…尊すぎる神投稿を発見、いいね！",
                "通りすがりだけど、スルーできなかった！",
                "みんな早くこれ見て！撮影センスが神！",
                "このカメラテク、ガチで羨ましいレベル",
                "構組が神すぎる！早くやり方教えて！",
                "キャラと衣装と背景が完全にマッチ！",
                "また他人の圧倒的な神画質に驚く一日",
                "ここどこ？めちゃ綺麗！聖地巡礼する",
                "どの写真も良すぎて壁紙に直行レベル！",
                "このライティングエグすぎ！神Mod？",
                "めっちゃ癒やされた…！",
                "もっと投稿して！こういうの大好物！",
                "今日のTL巡り、この投稿で最高になった",
                "これからも応援してます！投稿期待！",
                "投稿主のプロフ、他にも良い写真ある？",
                "今日分の美図を無事に吸収！",
                "気づいたら手が止まってずっと見入ってた",
                "前排でウォッチ、投稿主さんご馳走様です",
                "タイムライン流し見してたけど止まった！",
                "今のうちに推しとこ！これ絶対バズる",
                "100点満点中なら、101点差し上げます",
                "それな。",
                "ガチで共感。"
            ],
            "ko_KR": [
                "역대급 포스팅!! 좋아요 백만개 각이다",
                "존잘님 포스팅 앞에 무릎 꿇고 차 대령",
                "이거 무조건 뜬다!! 성지순례 왔어요",
                "스샷 장인 인정! 제 마음속에 저장요",
                "대박.. 또 하나의 보물 계정 찾았다!",
                "개안함.. 좋아요 북마크 갈겼습니다",
                "이번 포스팅 너무 고트해서 극락 감",
                "와 미쳤다.. 들어오자마자 미모 폭격",
                "우우.. 갓벽한 포스팅 발견! 좋아요!",
                "지나가던 사람인데 댓글 안 쓸 수 없다",
                "다들 빨리 이것 좀 봐! 촬영 센스 굿",
                "이 카메라 연출력 진심 닮고 싶다ㅠㅠ",
                "구도가 예술임! 제발 튜터 좀 주세요",
                "캐릭터 의상 배경 삼박자 완전 대박!",
                "오늘도 남의 집 화질에 기죽는 하루ㅠㅠ",
                "여기 어디야? 존예.. 나도 찍으러 간다",
                "사진 다 대박이라 폰 배경화면 직행!",
                "이 조명 감성 무엇? 고급 필터 쓴 건가",
                "완전 힐링된다.. 심장 폭행당함",
                "더 올려주세요!! 현기증 난단 말예요",
                "오늘 덕질은 이 포스팅 덕분에 완벽~",
                "앞으로도 열일해주세요! 고퀄 기대!",
                "주인장 프로필에 다른 사진도 있나?",
                "오늘분의 미주 영양분 흡수 완료!",
                "나도 모르게 스크롤 멈추고 보는 중",
                "미리 입덕합니다! 이거 무조건 떡상",
                "100점 만점에 점수 더 드림! 101점",
                "ㄹㅇ공감",
                "진심 그거 맞지"
            ],
            "en_US": [
                "Incredible post! Makes me wanna smash like!",
                "First row! Serving tea to the master gamer~",
                "This is gonna blow up! Camped here early.",
                "Amazing photo skills! Fully supporting this!",
                "Omg, just found another treasure account!",
                "Insane! Immediately hit like and bookmark!",
                "This post is literally the GOAT. Love it!",
                "Help, blinded by this absolute masterpiece!",
                "Wow, found an amazing post, instant like!",
                "Just passing by, but couldn't ignore this!",
                "Everyone look at this! God-tier photo skills!",
                "Im so jealous of this camera technique, ngl.",
                "Godly composition! Need a tutorial asap!",
                "Char, outfit, and scene are perfect match!",
                "Another day amazed by someone else's 4K.",
                "Where is this? So beautiful, gotta visit!",
                "Every pic is wallpaper material. Love it!",
                "This lighting is insane! Any cool filters?",
                "So healing! This totally made my day.",
                "Post more! I absolutely love your content.",
                "My scrolling experience today became so good~",
                "Keep it up! Looking forward to more posts!",
                "Any other good pics on creator's profile?",
                "Successfully absorbed today's beauty dose!",
                "Couldn't help but stop and stare so long!",
                "Watching from front row. Thanks for feast!",
                "Was scrolling endlessly till I saw this lmao",
                "Bookmarking this! Feeling like it'll viral!",
                "101 out of 100! You nailed it, creator!",
                "Totally agree with this",
                "Real."
            ],
            "es_ES": [
                "¡Tremendo post! ¡Daría mil likes ya!",
                "¡Primer! Traigo un café para el maestro~",
                "¡Esto va a petar! Me quedo aquí temprano",
                "¡Qué fotaza! Tienes todo mi apoyo, crack!",
                "¡Dios, acabo de encontrar una cuenta joya!",
                "¡Qué loco! Like y guardado inmediatamente!",
                "Este post es literalmente el GOAT. ¡Amo!",
                "¡Ayuda, quedé ciego con tanto arte!",
                "Wow, encontré un post increíble, ¡like!",
                "Iba de paso, ¡pero no podía ignorar esto!",
                "¡Miren esto todos! ¡Foto de nivel dios!",
                "Qué envidia de técnica con la cámara, fr",
                "¡Composición divina! ¡Pasa el tutorial ya!",
                "¡Personaje, outfit y mapa pegan genial!",
                "Otro día siendo humillado por calidad ajena",
                "¿Dónde es esto? Qué hermoso, ¡tengo que ir!",
                "Cada foto sirve para fondo de pantalla. Dios",
                "¡Qué iluminación! ¿Usas algún filtro top?",
                "¡Qué paz da! Esto me alegró el día hoy.",
                "¡Sube más! Me fascina este contenido.",
                "Navegar hoy por aquí mejoró muchísimo~",
                "¡Sigue así! ¡Esperando más posts, crack!",
                "¿Habrá más fotos buenas en tu perfil?",
                "¡Dosis de belleza del día recibida, top!",
                "¡No pude evitar mirar por un buen rato!",
                "Mirando en primera fila. ¡Gracias por arte!",
                "Estaba scrolleando sin parar hasta ver esto",
                "¡Me guardo esto! ¡Se va a hacer viral!",
                "¡Un 101 de 100! ¡Te la rifaste, creador!",
                "Totalmente de acuerdo con esto",
                "Real."
            ],
            "pt_BR": [
                "Post incrível! Quero dar mil likes já!",
                "Primeiro! Trazendo café pro mestre aqui~",
                "Isso vai hitar! Cheguei cedo pra ver.",
                "Que fotão! Tem todo meu apoio, mano!",
                "Meu Deus, achei uma conta relíquia!",
                "Que insano! Curtido e salvo na hora!",
                "Esse post é o GOAT. Estou apaixonado!",
                "Socorro, fui bombardeado por tanta beleza!",
                "Uau, achei um post incrível, like certo!",
                "Estava de passagem, mas não deu pra ignorar",
                "Olhem isso galera! Foto de nível deus!",
                "Que inveja dessa câmera, na moral.",
                "Composição divina! Passa o tutorial pfv!",
                "Personagem, roupa e mapa deram match!",
                "Mais um dia humilhado pelo 4K dos outros.",
                "Onde é isso? Lindo demais, quero ir!",
                "Cada foto serve de wallpaper. Amei!",
                "Que iluminação insana! Usou algum mod?",
                "Que paz! Isso salvou meu dia hoje.",
                "Posta mais! Amo esse tipo de conteúdo.",
                "Minha timeline ficou 10x melhor hoje~",
                "Continua assim! No aguardo de mais posts!",
                "Será que tem mais relíquias no perfil?",
                "Dose diária de beleza absorvida com sucesso",
                "Não deu pra passar direto, parei pra olhar",
                "Na primeira fila apreciando essa obra!",
                "Estava no scroll infinito até ver isso kkk",
                "Já salvei! Sinto que isso vai hitar muito",
                "Nota 101 de 100! Vc é gigante, criador!",
                "Concordo totalmente com isso",
                "Real."
            ],
            "de_DE": [
                "Mega Post! Bin total begeistert!",
                "Einfach der Hammer, danke für diesen Inhalt!",
                "Das muss man gesehen haben, richtig gut!",
                "Unglaubliche Aufnahme, top gemacht!",
                "Bin gerade hier gelandet und wow, tolles Bild!",
                "Definitiv geliked und gespeichert!",
                "Dein Stil ist einfach bezaubernd!",
                "Wie hast du das fotografiert? Echt stark!",
                "Beste Bilder des Tages, danke!",
                "Bitte mehr davon, liebe den Vibe!",
                "Habe das Bild gesehen – einfach klasse.",
                "Bin zufällig hier, musste kommentieren!",
                "Absolute Empfehlung, schaut euch das an!",
                "Wie schaffst du diese Qualität? Beeindruckend!",
                "Das Licht ist ja fantastisch!",
                "Du hast meinen Tag gerettet, danke!",
                "Einfach nur wunderschön.",
                "Das Bild hat definitiv Wallpapermaterial!",
                "Dein Profil ist eine Goldgrube!",
                "Einfach weiter so, sehr motivierend!"
            ],
            "fr_FR": [
                "Post incroyable, j'adore !",
                "Superbe contenu, merci pour le partage !",
                "C'est magnifique, bravo pour cette pépite !",
                "Photo tellement réussie, félicitations !",
                "Gros coup de cœur pour ce post !",
                "Déjà liké et sauvegardé, c'est génial !",
                "C'est tellement esthétique, j'adore !",
                "Quelle ambiance ! Tu as des astuces ?",
                "Absolument sublime, je suis fan !",
                "Encore, encore ! On veut voir plus !",
                "Passé par hasard, il fallait commenter !",
                "Ce cliché est à couper le souffle.",
                "La qualité est incroyable, je suis scotché.",
                "Très élégant, ça change du quotidien !",
                "Une vraie source d'inspiration, merci !",
                "Cette lumière est parfaite, sublime.",
                "Directement dans mes favoris !",
                "Ton compte est une vraie pépite, je m'abonne !",
                "Magnifique, ça fait du bien aux yeux !",
                "Continue comme ça, c'est superbe !"
            ],
            "ru_RU": [
                "Шикарный пост, просто восторг!",
                "Это гениально, спасибо за контент!",
                "Ого, какая красота! Однозначно лайк.",
                "Снимок просто класс, мастерски!",
                "Попал сюда случайно и залип надолго!",
                "Уже в избранном, это шедевр!",
                "Очень эстетично, глаз не оторвать!",
                "Как тебе удалось так поймать свет? Круто!",
                "Лучший пост, что я видел сегодня!",
                "Жду продолжения, очень нравится!",
                "Заглянул в профиль, там всё такое крутое!",
                "Просто 10 из 10, нет слов!",
                "Один лайк маловато будет!",
                "Атмосфера на высоте, очень вдохновляет.",
                "Вау, это очень профессионально!",
                "Спасибо за такой позитив!",
                "Прям как обои на рабочий стол, очень красиво.",
                "Настоящая находка, спасибо!",
                "Очень круто, продолжай в том же духе!",
                "Определенно, это лучший контент на сегодня!"
            ],
        },
        "preset_posts":{
            "zh_CN":[
                "随手一拍",
                "太美丽啦",
                "这角色这衣服这场景绝配",
                "今日打卡",
                "每张都好看到可以当壁纸",
                "这光影绝了",
                "被治愈到了",
                "继续加油高产中",
                "主页还有其他好看的",
                "今日份的美图",
                "吃得太好了吧",
                "直觉告诉我这篇在呗果要爆",
                "太真实了",
            ],
            "zh_TW": [
                "分享一張隨手拍",
                "美到失語！",
                "今天又是被治癒的一天",
                "這角色衣服跟場景根本是絕配！",
                "今日份唄果打卡，踩個足跡",
                "精選美圖！每張都好看得可以當桌布",
                "這個神仙光影真的超絕，愛了",
                "心靈被治癒的瞬間，分享給大家",
                "最近瘋狂高產中！快來主頁督促我",
                "原PO主頁還有其他好看的，不看後悔",
                "今日份美圖已送達，請注意查收",
                "今天大佬吃得太好了吧，大飽眼福",
                "直覺告訴我，這篇貼文在唄果會爆！",
                "太真實了",
                "這完全就是我的日常"
            ],
            "ja_JP": [
                "日常",
                "ふらっと一枚パシャリ",
                "マジで綺麗すぎる…！",
                "本日の神コーデ組み合わせ",
                "今日も元気にログイン",
                "そのまま壁紙にできそうなレベル",
                "このライティング、神がかってる！",
                "めちゃくちゃ癒された…",
                "心が浄化された",
                "今日も元気に投稿更新！",
                "遅くなりました！マイページも見てね",
                "本日分の美図をお届け",
                "今日のインゲームはご馳走だな！",
                "この投稿、バズりそうな予感がする",
                "ガチで共感する日常",
                "リアルすぎて草",
            ],
            "ko_KR": [
                "그냥 가볍게 한 컷",
                "진짜 너무 예쁘다!",
                "오늘자 완벽한 조합",
                "오늘도 출석 체크",
                "보자마자 바로 배경화면 각",
                "이번 조명 진짜 미쳤다!",
                "보기만 해도 힐링되는 기분",
                "오늘도 1일 1포스팅 완료!",
                "늦었지만 업로드! 홈에 사진 더 많아요",
                "오늘치 눈정화용 미포",
                "오늘 인게임에서 호강하네!",
                "이 게시물 왠지 떡상할 필인데?",
                "이거 진짜 찐이다.",
            ],
            "en_US": [
                "Just a casual pic", 
                "Absolutely gorgeous!",
                "Today's perfect combo",
                "Daily check-in",
                "Instant wallpaper material",
                "This lighting is insane!",
                "Totally blessed by this view",
                "Another day, another post!",
                "Late to the party! More pics on my feed",
                "My daily dose of eye candy",
                "Eating good in-game today!",
                "I feel like this one's gonna blow up!",
                "Too real.",
            ],
            "es_ES": [
                "Solo una foto casual",
                "¡Qué cosa más bonita!",
                "Combinación perfecta de hoy",
                "Fichando por hoy",
                "Directo para fondo de pantalla",
                "¡Menuda iluminación de locos!",
                "Totalmente curado con esto",
                "¡Una publicación más para el feed!",
                "¡Ya está! Más fotos en mi perfil.",
                "Mi dosis diaria de fotitos",
                "¡Qué banquete me he dado hoy!",
                "Presiento que este post va a lo más alto",
                "Real como la vida misma",
            ],
            "pt_BR": [
                "Apenas um clique casual", 
                "Que coisa mais linda!",
                "Combinação perfeita de hoje",
                "Check-in do dia",
                "Direto para o wallpaper",
                "Que iluminação absurda!",
                "Totalmente curado(a) por isso",
                "Mais um post para o feed!",
                "Finalmente! Mais fotos no meu perfil.",
                "Minha dose diária de fotos",
                "Comendo muito bem no jogo hoje!",
                "Sinto que esse post vai bombar!",
                "Real até demais",
            ],
            "de_DE": [
                "Einfach mal festgehalten.",
                "Wunderschön!",
                "Outfit und Szene passen perfekt.",
                "Ein kleiner Ort, ein großer Moment.",
                "Perfekt als Wallpaper geeignet.",
                "Das Licht ist einfach der Wahnsinn.",
                "Richtig beruhigend.",
                "Bitte mehr davon!",
                "Schau auch in mein Profil!",
                "Die Highlights des Tages.",
                "Einfach nur lecker!",
                "Wird bestimmt viral gehen!",
                "So unglaublich realistisch."
            ],
            # 法语 (fr_FR)
            "fr_FR": [
                "Juste un cliché pris sur le vif.",
                "Tellement magnifique !",
                "Tenue et lieu parfaits.",
                "Un petit souvenir.",
                "Parfait pour un fond d'écran.",
                "Cette lumière est divine.",
                "Ça fait du bien !",
                "Encore plus de contenu !",
                "Découvre le reste sur mon profil.",
                "Le beau du jour.",
                "Un pur régal pour les yeux.",
                "Ça va devenir viral, c'est sûr !",
                "C'est tellement réaliste."
            ],
            # 俄语 (ru_RU)
            "ru_RU": [
                "Просто фото на память.",
                "Невероятно красиво!",
                "Идеальное сочетание.",
                "Отметился здесь.",
                "Отличные обои для экрана.",
                "Свет просто потрясающий.",
                "Настоящая терапия.",
                "Жду новых работ!",
                "Загляни ко мне в профиль.",
                "Красота на сегодня.",
                "Настоящее эстетическое наслаждение.",
                "Этот пост точно залетит в топ!",
                "Очень реалистично."
            ],
        },
    }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "呗果智能体"
        self.description = "自动模式下将自动发帖回帖点赞\n助手模式下可辅助生成各种文案\n支持调用支持图片输入的模型生成文案"
        self.icon = FluentIcon.HEART
        self.instructions = """【呗果智能体】\n自动模式下将自动发帖回帖点赞；\n助手模式下可辅助生成文案。\n支持调用支持图片输入的模型生成文案。\n项目开发版地址与配置教程：<a href="https://github.com/HazukiKaguya/BagelAIToolsDev">呗果智能体</a>"""
        bagel_supported_languages =["zh_CN", "zh_TW", "ja_JP", "en_US", "es_ES", "de_DE", "fr_FR"]
        # bagel_supported_languages =["zh_CN", "zh_TW", "ja_JP", "ko_KR", "en_US", "es_ES", "de_DE", "fr_FR", "ru_RU"]
        get_lang = get_app_locale()
        temp_lang = "zh_CN"
        if get_lang:
            temp_lang = get_lang
            if get_lang == "ko_KR":
                temp_lang = "en_US"
                self.log_info("ko_KR not support now, switch to en_US")
        self.model_prompt = self.BASE_BAGEL_I18N["model_prompt"][temp_lang]
        self.default_config.update(
            {
                self.CONF_GAME_LANG : temp_lang,
                self.CONF_MODEL: False,
                self.CONF_HELPER_MODE: False,
                self.CONF_AUTO_AICONFIG: ["自动发帖", "自动回帖", "自动按赞", "过滤水贴"],
                self.CONF_MODEL_URL: "",
                self.CONF_MODEL_API: "",
                self.CONF_MODEL_NAME: "qwen/qwen3-vl-4b",
                self.CONF_PROMPT_REPLY: self.model_prompt["REPLY"],
                self.CONF_PROMPT_POST_TITLE: self.model_prompt["POST_TITLE"],
                self.CONF_PROMPT_POST_CONTENT: self.model_prompt["POST_CONTENT"],
            }
        )
        self.config_description.update(
            {
                self.CONF_GAME_LANG : "游戏语言/遊戲語言/ゲーム言語/게임 언어\nGame Language/Язык игры",
                self.CONF_MODEL: "关闭后将降级使用本地词库抽取发帖回复文案",
                self.CONF_HELPER_MODE: "开启助手模式后，将只会辅助生成文案",
                self.CONF_AUTO_AICONFIG: "智能体模式选项\n自动回帖会同时点赞",
                self.CONF_MODEL_URL: "使用模型根据图片生成文案，推荐本地部署",
                self.CONF_MODEL_API: "未设置请留空，请勿泄露API_Key！",
                self.CONF_MODEL_NAME: "推荐qwen/qwen3-vl-4b，显存占用较小",
                self.CONF_PROMPT_REPLY: "回复模块提示词，请先调试好文案再使用",
                self.CONF_PROMPT_POST_TITLE: "发帖标题模块提示词，请先调试好文案再使用",
                self.CONF_PROMPT_POST_CONTENT: "发帖内容模块提示词，请先调试好文案再使用",
            }
        )
        options = ["自动发帖", "自动回帖", "自动按赞", "过滤水贴"]
        self.config_type.update(
            {
                self.CONF_GAME_LANG: {
                    "type": "drop_down",
                    "options": bagel_supported_languages,
                },
                self.CONF_AUTO_AICONFIG: {"type": "multi_selection", "options": options},
            }
        )
        self.interacted_posts = set()
        self.reply_count = 0
        self.post_count = 0
        self.like_count = 0
        self.is_running = False
        self.nowview_post = ""
        self.nowview_poster = ""

    # ==========================================
    # 主模块
    # ==========================================

    # 模式判断、异常处理
    def run(self):
        super().run()
        target_lang = self.config.get(self.CONF_GAME_LANG, "zh_CN")
        self.bagel_ocr = self.BASE_BAGEL_I18N["bagel_ocr"][target_lang]
        self.preset_replies = self.BASE_BAGEL_I18N["preset_replies"][target_lang]
        self.preset_posts = self.BASE_BAGEL_I18N["preset_posts"][target_lang]
        self.model_prompt = self.BASE_BAGEL_I18N["model_prompt"][target_lang]
        self.is_running = False
        self.gallery_total_count = 1
        self.reply_count = 0
        self.post_count = 0
        self.like_count = 0
        self.info_clear()
        self.log_info("脚本初始化完成！")
        self.sleep(2.56)
        is_helper_mode = self.config.get(self.CONF_HELPER_MODE, True)
        if is_helper_mode:
            self.info_set(self.INFO_HELPER_COUNT, 0)
            self.log_info("当前运行在：呗果文案助手模式")
            self.sleep(1.14)
            target_action = self.do_helper_run
            error_msg = "呗果文案助手出错: "
        else:
            self.info_set("成功发帖次数", 0)
            self.info_set("成功回复次数", 0)
            self.info_set(self.INFO_LIKE_COUNT, 0)
            self.ensure_main(esc=True, time_out=60)

            target_action = self.do_run
            error_msg = "呗果小工具出错"
        try:
            target_action()
        except TaskDisabledException:
            pass
        except Exception as e:
            self.log_error(error_msg, e)
            raise

    # 文案助手模式
    def do_helper_run(self):
        self.is_running = False
        self.log_info("【F1】🟢启动 /🔴暂停 呗果文案助手")
        # 注册快捷键监听
        listener = self.setup_helper_hotkeys()
        try:
            while self.enabled:
                if not self.is_running:
                    self.sleep(1.14)
                    continue
                if self.find_area(area="reply_area"):
                    self.reply_helper()
                    self.info_add(self.INFO_HELPER_COUNT, 1)
                    self.sleep(1.14)
                    continue
                elif self.find_area(area="post_check_area"):
                    if self.find_area(area="post_photo_zone_area"):
                        self.sleep(1.14)
                        continue
                    post_title_area = self.find_area(area="post_title_area")
                    if post_title_area:
                        self.post_helper(area=post_title_area, post_type="title")
                        self.info_add(self.INFO_HELPER_COUNT, 1)
                        self.sleep(1.14)
                        continue
                    post_content_area = self.find_area(area="post_content_area")
                    if post_content_area:
                        self.post_helper(area=post_content_area, post_type="content")
                        self.info_add(self.INFO_HELPER_COUNT, 1)
                        self.sleep(1.14)
                        continue
                    self.sleep(1.14)
                    continue
                else:
                    if self.in_team_and_world():
                        self.log_info("🔴 检测在大世界，呗果文案助手自动暂停！")
                        self.is_running = False
                        continue
                    self.sleep(1.14)
        finally:
            # 卸载快捷键监听
            self.is_running = False
            if listener and listener.running:
                listener.stop()

    # 自动智能体模式
    def do_run(self):
        self.auto_config_list = self.config.get(self.CONF_AUTO_AICONFIG, [])
        # 自动发帖
        ignore_tags = {"过滤水贴"}
        active_tasks = [task for task in self.auto_config_list if task not in ignore_tags]
        if active_tasks:
            self.open_phone()
            self.sleep(1.28)
        if "自动发帖" in self.auto_config_list:
            self.enter_app(app="camera")
            self.sleep(1.28)
            self.process_camera_action(action="take_photo", number=5)
            self.sleep(1.28)
            self.open_phone()
            self.enter_app(app="bagel")
            self.sleep(1.28)
            self.post_module()
            self.log_info("已完成发帖任务！")
            self.sleep(1.28)
            self.open_phone()
            self.sleep(1.28)
            self.enter_app(app="camera")
            self.sleep(1.28)
            self.process_camera_action(action="clear_album", number=5)
            self.sleep(1.28)
            self.open_phone()
            self.sleep(1.28)
        # 自动互动
        if "自动回帖" in self.auto_config_list or "自动按赞" in self.auto_config_list:
            self.enter_app(app="bagel")
            self.sleep(1.28)
            self.reply_like_module()
            self.log_info("已完成回帖按赞任务！")
            self.sleep(1.28)
            self.open_phone()
        self.sleep(1.28)
        self.enter_app(app="bagel")

    # ==========================================
    # 文案助手模块
    # ==========================================

    # 回复助手
    def reply_helper(self):
        post_title = self.find_area(area="post_title", action="get_text")
        if not post_title:
            return False
        post_title_text = post_title[0].name
        poster_name = self.find_area(area="poster_name", action="get_text")
        poster_name_text = "呗主"
        if poster_name:
            poster_name_text = poster_name[0].name
        self.sleep(0.20)
        if (post_title_text == self.nowview_post and self.nowview_poster == poster_name_text) or (
            post_title_text in self.interacted_posts
        ):
            self.sleep(0.50)
            return False
        self.sleep(0.20)
        btn_reply_area = self.find_area(area="reply_area", action="click")
        self.operate_click(btn_reply_area)
        self.sleep(0.20)
        my_reply_text = self.generate_reply_content(
            title_text=post_title_text, author_name=poster_name_text
        )
        self.sleep(0.20)
        self.input_text(my_reply_text)
        self.nowview_post = post_title_text
        self.nowview_poster = poster_name_text
        self.sleep(0.20)
        return True

    # 发帖助手
    def post_helper(self, area=None, post_type="title"):
        if not area:
            return False
        self.sleep(0.50)
        self.operate_click(area)
        self.sleep(0.50)
        # 发帖
        my_reply_text = self.generate_post_content(generate_type=post_type)
        self.sleep(0.50)
        self.input_text(my_reply_text)
        if post_type == "title":
            self.nowview_post = my_reply_text
        self.sleep(0.50)
        return True

    # 注册快捷键
    def setup_helper_hotkeys(self):
        """使用现有的 pynput 注册全局快捷键（返回 listener 实例以便后续销毁）"""
        if getattr(self, "_global_hotkey_listener", None) is not None:
            return self._global_hotkey_listener
        import ctypes

        from pynput import keyboard

        try:
            from pynput._util import win32

            if hasattr(win32, "KeyTranslator"):
                win32.KeyTranslator._ToUnicodeEx.argtypes = [
                    ctypes.c_uint,
                    ctypes.c_uint,
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                    ctypes.c_int,
                    ctypes.c_uint,
                    ctypes.c_void_p,
                ]
        except Exception:
            pass

        def on_release(key):
            try:
                if key == keyboard.Key.f1:
                    self.is_running = not self.is_running
                    if self.is_running:
                        self.log_info("🟢 呗果文案助手已就绪！")
                    else:
                        self.log_info("🔴 呗果文案助手已暂停！")
            except Exception as e:
                self.log_error(f"快捷键响应异常: {e}")

        listener = keyboard.Listener(on_release=on_release)
        listener.start()
        return listener  # 把实例丢出去

    # ==========================================
    # 智能体模快 回帖按赞相关
    # ==========================================
    _RE_PATTERN_WATER = re.compile(
        r"(互评|互互互|互赞|互粉|求.*回|秒回|点赞|回赞|互.*关|留名|顶帖|\bdd\b)", re.IGNORECASE
    )
    _RE_PATTERN_SPAM = re.compile(r"(^[a-z\s]+$|^[0-9\s]+$|^[\W_]+$)", re.IGNORECASE)
    _RE_SPAM_CLEANER = re.compile(r"[\d\s\=\÷\+\*\/\\|\[\]\{\}\(\)\<\>\?¿¡§¶†‡■□▲△▼▽◆◇○●•★☆\-]")
    _WHITELIST_STRICT_EXACT = {
        # 现代网络核心双字心态表达
        "服了", "呃呃", "草生", "确实", "qs", "gg", "fr", "4k","xd",":)", "(:",
        # 现代网络核心单字心态表达
        "6", "六",  "绷", "典", "乐", "草",  "喂", "哈", "神", "大", "巨", "顶", "寄", "润", "麻", "躺", 
    }
    _WHITELIST_SPECIAL_MEMES = {
        # 经典数字梗
        "114514", "1919810", "2333", "666", "520", "1314", "886", "555", "7777777",
        # 拼音首字母缩写
        "awsl", "yyds", "nsdd", "xswl",  "dddd", "jbl", 
        # 国际化网络黑话
        "vrc",  "lol", "lmao", "rofl", "omg", "wtf", "wth", "wip", "afk", "brb", "thx", "mvp", "npc", "ㄹㅇ", "ㄱㅇㅇ", "www",
        # 高频纯符号/标点符号流
        "???", "!!!", "!?",
        # 经典颜文字
        "qaq", "orz", "otz", "owo", "qwq", "tat",
    }
    _RE_ALBUM_PREFER = re.compile(r"(\d+)[/|]\d+")
    _RE_ALBUM_BACKUP = re.compile(r"(?:历史(?:记录)?|歴史(?:記錄)?|履歴|기록|Verlauf|История|Histor\w*)[\s\-_]?(\d{1,2})")
    _RE_ALBUM_LAST_RESORT = re.compile(r"(\d{1,2})")

    # 回帖按赞操作流程
    def reply_like_module(self):
        if "自动回帖" in self.auto_config_list:
            self.log_info("进行自动回复，同时会按赞")
        elif "自动按赞" in self.auto_config_list:
            self.log_info("进行自动按赞")
        else:
            return

        def find_sort_menu_new():
            return self.find_area(area="sort_menu_area_done")

        is_page_ok = False
        while self.enabled and (self.reply_count < 5 or self.like_count < 5):
            if not find_sort_menu_new():
                self.sleep(1.00)
                btn_sort = self.find_area(area="sort_menu_area", action="click")
                self.wait_until(
                    lambda: self.find_area(area="sort_menu_list"),
                    pre_action=lambda btn=btn_sort: self.operate_click(btn, interval=3.14),
                    time_out=30,
                    raise_if_not_found=True,
                )
                self.sleep(3.00)
                btn_sort_list = self.find_area(area="sort_menu_select", action="click")
                self.wait_until(
                    lambda: not self.find_area(area="sort_menu_list"),
                    pre_action=lambda btn=btn_sort_list: self.operate_click(btn, interval=3.14),
                    time_out=30,
                    raise_if_not_found=True,
                )
                self.sleep(3.00)
                continue
            if is_page_ok:
                self.sleep(1.14)
                self.scroll_relative(0.50, 0.50, -17)
                is_page_ok = False
                self.sleep(1.14)
                continue
            is_page_ok = self.process_current_page_posts()

    # 回帖按赞互动模块
    def process_current_page_posts(self):
        """互动模块

        `action` 设置为 reply 时，进行回帖操作；设置为 like 时，进行点赞操作。
        """
        posts = self.find_posts()

        if not posts:
            self.log_info("当前页面没有发现符合条件的优质帖子。")
            return True  # 告诉可以翻页了

        for i, post in enumerate(posts):
            if self.reply_count >= 5 and self.like_count >= 5:
                self.log_info("已完成自动回复按赞任务！")
                return False  # 只是返回掉，因为结束了
            if not self.find_area(area="reply_area"):
                self.log_info(f"正在点击目标帖子【{post.name}】")
                self.operate_click(post)
                self.sleep(3.00)  # 等待帖子内容加载
            post_title = self.find_area(area="post_title", action="get_text")
            if not post_title:
                if self.find_area(area="reply_area"):
                    self.send_key("esc")
                self.sleep(2.56)
                continue
            post_title_text = post_title[0].name
            if "过滤水贴" in self.auto_config_list:
                filtered_result = self.posts_filter([post_title[0]])
                if not filtered_result:
                    self.send_key("esc")  # 物理按下 ESC 返回列表
                    self.sleep(2.56)      # 挂机脚本的标准安全物理冷却
                    continue
            if post_title_text in self.interacted_posts:
                self.send_key("esc")
                self.sleep(2.56)
                continue
            if "自动回帖" in self.auto_config_list and self.reply_count < 5:
                is_reply = self.reply_helper()
                if not is_reply:
                    if self.find_area(area="post_title", action="get_text"):
                        self.send_key("esc")
                    self.sleep(2.56)
                    continue
                self.sleep(2.56)
                self.operate_click(0.90, 0.90)
                self.sleep(0.42)
                self.reply_count += 1
                self.info_add("成功回复次数", 1)
                self.interacted_posts.add(post_title_text)
                self.sleep(0.42)
                self.operate_click(0.53, 0.85)
                self.like_count += 1
                self.info_add(self.INFO_LIKE_COUNT, 1)
            elif "自动按赞" in self.auto_config_list and self.like_count < 5:
                # 点赞
                self.sleep(0.2)
                self.operate_click(0.53, 0.85)
                self.like_count += 1
                self.info_add(self.INFO_LIKE_COUNT, 1)
                self.interacted_posts.add(post_title_text)
            else:
                pass  # 万一以后准备加点啥
            self.sleep(1.14)
            if self.find_area(area="reply_area"):
                self.send_key("esc")
            self.sleep(2.56)
        self.log_info("本页抓取到的所有帖子已全部处理完毕！")
        return True  # 告诉可以翻页了

    # 找贴模块
    def find_posts(self):
        """找贴模块

        1. 如果关闭了反水贴开关，不做任何过滤，返回区域内所有OCR结果。
        2. 开启反水贴时，过滤掉互赞类和无意义类水贴，返回过滤后的OCR结果。
        """
        pre_posts = self.wait_ocr(0.17, 0.30, 0.99, 0.90, time_out=1.14, raise_if_not_found=False)
        all_posts = self.filter_author_names_smart(pre_posts, self.screen_width, self.screen_height)

        if "过滤水贴" not in self.auto_config_list:
            return all_posts

        # 确保 all_posts 是列表结构方便后面遍历
        clean_posts = self.posts_filter(all_posts)
        return clean_posts if clean_posts else None

    # 作者名过滤模块
    def filter_author_names_smart(self, ocr_results, x_threshold=0.03, y_threshold=0.04):
        """
        专为框架 Box 类定制的空间智能过滤器（100% 避开属性缺失坑）
        """
        if not ocr_results:
            return []

        processed_items = []

        for box in ocr_results:
            # 依据 Box.__init__ 文档，利用 x, y, width, height 计算几何中心与边界
            cx_ratio = box.x + (box.width / 2)
            ymin_ratio = box.y
            ymax_ratio = box.y + box.height

            # 文档明确指明 Box.name 存储的就是识别出的文本
            text = box.name

            processed_items.append(
                {
                    "cx_ratio": cx_ratio,
                    "ymin_ratio": ymin_ratio,
                    "ymax_ratio": ymax_ratio,
                    "box_obj": box,
                    "text": text,
                }
            )

        # 1. 按纵坐标 Y 从上到下排序
        processed_items.sort(key=lambda item: item["ymin_ratio"])

        keep_flags = [True] * len(processed_items)

        # 2. 双指针空间碰撞过滤
        for i in range(len(processed_items)):
            if not keep_flags[i]:
                continue
            upper_item = processed_items[i]

            for j in range(i + 1, len(processed_items)):
                if not keep_flags[j]:
                    continue
                lower_item = processed_items[j]

                # 判定横向中心点是否对齐（x 轴偏离在阈值内）
                x_aligned = abs(upper_item["cx_ratio"] - lower_item["cx_ratio"]) < x_threshold
                # 判定纵向是否挨着（下方的左上角 Y 减去上方的右下角 Y，看间距是否在阈值内）
                y_adjacent = (
                    0 <= (lower_item["ymin_ratio"] - upper_item["ymax_ratio"]) < y_threshold
                )

                if x_aligned and y_adjacent:
                    # 标记下方的作者名 Box 不需要保留
                    keep_flags[j] = False
                    break

        # 3. 回传：提取出留下来的原装 Box 对象列表给后面的循环
        return [
            processed_items[idx]["box_obj"]
            for idx in range(len(processed_items))
            if keep_flags[idx]
        ]

    # 水帖过滤模块
    def posts_filter(self, all_posts):
        if not all_posts:
            return None

        # 确保 all_posts 是列表结构方便后面遍历
        if not isinstance(all_posts, list):
            all_posts = [all_posts]

        clean_posts = []

        for post in all_posts:
            # 拿到当前帖子识别出来的文本内容
            text = getattr(post, "name", "").strip()
            if not text:
                continue

            # 完全符合白名单则放行
            if (text.lower() in self._WHITELIST_STRICT_EXACT or 
                text.lower() in self._WHITELIST_SPECIAL_MEMES):
                clean_posts.append(post)
                continue
            
            # 拦截非贴文
            if len(text) < 3:
                continue

            if self._RE_PATTERN_SPAM.match(text):
                if (text.lower() not in self._WHITELIST_STRICT_EXACT and 
                    text.lower() not in self._WHITELIST_SPECIAL_MEMES):
                    self.log_info(f"【拦截】垃圾贴: '{text}'")
                    continue

            meaningful_text = self._RE_SPAM_CLEANER.sub("", text).strip()

            # 检查是否包含互赞关键词
            if self._RE_PATTERN_WATER.search(meaningful_text):
                self.log_info(f"【拦截】互赞贴: '{text}'")
                continue
            
            # meaningful_text 很少的情况
            is_strict_match = meaningful_text.lower() in self._WHITELIST_STRICT_EXACT
            if len(meaningful_text) < 3:
                is_sub_match = any(meme in text.lower() for meme in self._WHITELIST_SPECIAL_MEMES)
                if is_strict_match or is_sub_match:
                    clean_posts.append(post)
                    continue
                else:
                    self.log_info(f"【拦截】垃圾贴: '{text}'")
                    continue

            # 检查是否是纯无意义乱码/凑字数字符
            if self._RE_PATTERN_SPAM.match(meaningful_text):
                # 同样执行双轨制特赦校验
                is_strict_match = meaningful_text.lower() in self._WHITELIST_STRICT_EXACT
                is_sub_match = any(meme in meaningful_text.lower() for meme in self._WHITELIST_SPECIAL_MEMES)
                if is_strict_match or is_sub_match:
                    self.log_info(f"【放行】清洗文本 '{meaningful_text}' 属于已知白名单梗，特赦放行")
                    clean_posts.append(post)
                    continue
                else:
                    self.log_info(f"【拦截】垃圾贴(清洗文本乱码): '{text}'")
                    continue

            # 正常帖子进入有效列表
            clean_posts.append(post)

        # 返回清洗干净后的帖子列表，如果没有则返回 None
        return clean_posts if clean_posts else None

    # ==========================================
    # 智能体模快 发帖相关
    # ==========================================

    # 发帖操作流程模块
    def post_module(self):
        self.log_info("进行自动发帖")
        while self.enabled and self.post_count < 5:
            self.sleep(2.56)
            if not self.find_area(area="sort_menu_area"):
                self.sleep(0.50)
                self.open_phone()
                self.sleep(0.50)
                self.enter_app(app="bagel")
                self.sleep(5.14)
                continue
            self.wait_until(
                lambda: self.find_area(area="post_check_area"),
                pre_action=lambda: self.operate_click(0.05, 0.93, interval=3.14),
                time_out=30,
                raise_if_not_found=True,
            )
            self.log_info("进入发帖界面")
            self.sleep(1.14)
            if self.find_area(area="post_photo_zone_area"):
                btn_select_photo = self.find_area(area="post_photo_zone_area", action="click")
                self.wait_until(
                    lambda: not self.find_area(area="post_check_area"),
                    pre_action=lambda btn=btn_select_photo: self.operate_click(btn, interval=3.14),
                    time_out=30,
                    raise_if_not_found=True,
                )
                self.log_info("选择发帖用图片")
                self.sleep(1.14)
                # 这里写好选照片的方法
                self.select_latest_photos(
                    photo_new_count=self.post_count + 1, photo_total=self.gallery_total_count
                )
                self.sleep(0.50)
                btn_photo_confirm = self.find_area(area="post_photo_confirm", action="click")
                self.wait_until(
                    lambda: (
                        self.find_area(area="post_check_area")
                        and not self.find_area(area="post_photo_zone_area")
                    ),
                    pre_action=lambda btn=btn_photo_confirm: self.operate_click(btn, interval=3.14),
                    time_out=30,
                    raise_if_not_found=True,
                )
                self.log_info("发帖用图片选择完成")
            self.sleep(1.14)
            if (
                not self.process_bagel_post()
            ):  # 选完照片后调用发帖文案生成并发送方法，返回 True 则说明生成并发布成功了
                continue
            # 扫描“发布”按钮
            btn_post_confirm = self.find_area(area="post_confirm_area", action="click")
            self.sleep(0.50)
            self.wait_until(
                lambda: (
                    self.find_area(area="sort_menu_area")
                    and not self.find_area(area="post_check_area")
                ),
                pre_action=lambda btn=btn_post_confirm: self.operate_click(btn, interval=3.14),
                time_out=60,
                raise_if_not_found=True,
            )
            self.post_count += 1
            self.log_info("成功发帖")
            self.info_add("成功发帖次数", 1)
            self.sleep(5.14)

    # 选图块
    def select_latest_photos(self, photo_new_count=1, photo_total=1):
        """选图模块（单选）

        参数:
            photo_new (int): 代表第几张新图。
                             1 代表最新的一张
                             2 代表次新的一张，以此类推...
        """
        try:
            photo_total = int(photo_total)
        except (ValueError, TypeError):
            self.log_info(
                f"接收到非法的 photo_total: {photo_total} (类型: {type(photo_total).__name__})，已强制启用安全默认值 1"
            )
            photo_total = 1
        # 越界输入归正
        if photo_total > 36:
            photo_total = 36
        elif photo_total < 1:
            photo_total = 1
        if photo_new_count < 1:
            photo_new_count = 1
        elif photo_new_count > photo_total:
            photo_new_count = photo_total
        # 按从旧到新顺序的话是第几位，只会得到0-35的数
        photo_count = photo_total - photo_new_count
        # 根据总照片数归一化
        scroll_times = 0
        while photo_count > 11:
            photo_count -= 4
            scroll_times += 1
        photo_grid_locations = (
            (0.15, 0.25),
            (0.38, 0.25),
            (0.62, 0.25),
            (0.85, 0.25),  # 第一排 1-4
            (0.15, 0.50),
            (0.38, 0.50),
            (0.62, 0.50),
            (0.85, 0.50),  # 第二排 5-8
            (0.15, 0.75),
            (0.38, 0.75),
            (0.62, 0.75),
            (0.85, 0.75),  # 第三排 9-12
        )
        if scroll_times > 0:
            for _ in range(scroll_times):
                if not self.enabled:
                    return
                self.scroll_relative(0.50, 0.50, -8)
                self.sleep(0.25)
            self.sleep(1.00)
        target = photo_grid_locations[photo_count]

        self.log_info(f"正在点击第 {photo_new_count} 张最新图片），坐标: {target}")
        self.operate_click(*target)
        self.sleep(1.14)

    # 正式发帖模块
    def process_bagel_post(self):
        # 先用局部 OCR 确认自己真的在发帖界面
        if not self.find_area(area="post_check_area"):
            self.sleep(1.14)
            return False
        post_title_area = self.find_area(area="post_title_area")
        if post_title_area:
            self.post_helper(area=post_title_area, post_type="title")
        self.sleep(1.14)
        post_content_area = self.find_area(area="post_content_area")
        if post_content_area:
            self.post_helper(area=post_content_area, post_type="content")
        self.sleep(1.14)
        return True

    # 相机拍图删图模块
    def process_camera_action(self, action="clear_album", number=5):
        """拍图/删图模块（单选）

        参数:
            number (int): 代表拍/删几张图。
            action (str):
                - clear_album : 删图
                - take_photo  : 拍图
                    - phone_third : 手机第三人称
                    - phone_self  : 手机自拍
                    - uav_third   : 无人机第三人称
                    - uav_first   : 无人机第一人称
        """
        try:
            number = int(number)
            if number < 1:
                self.log_info(f"接收到非正整数的 number: {number} ，已强制启用默认值 5")
                number = 5
        except (ValueError, TypeError):
            self.log_info(
                f"接收到非法的 number: {number} (类型: {type(number).__name__})，已强制启用默认值 5"
            )
            number = 5

        if action == "clear_album":
            self.sleep(1.14)
            self.operate_click(0.035, 0.94)
            self.log_info("进入相册")
            self.sleep(1.14)
            current_total = self.get_gallery_total()
            if current_total <= number:
                self.log_info("照片总数小于或等于要删除的数量。")
                return True
            if current_total > 12:
                self.log_info("正在将相册推至最底部...")
                for _ in range(6):
                    self.scroll_relative(0.50, 0.50, -8)
                    self.sleep(0.20)
                self.sleep(1.00)
            else:
                self.log_info("总数小于等于12张，静态网格，无需滚动。")

            for i in range(number):
                if not self.enabled:
                    return False
                # 计算最新那张图的绝对索引
                photo_count = current_total - 1
                if current_total > 12:
                    # 如果总数大于12，说明页面此时钉在底部，利用减 4 映射到 0-11 的底部相对格子上
                    while photo_count > 11:
                        photo_count -= 4

                photo_grid_locations = (
                    (0.15, 0.25),
                    (0.38, 0.25),
                    (0.62, 0.25),
                    (0.85, 0.25),  # 0-3
                    (0.15, 0.50),
                    (0.38, 0.50),
                    (0.62, 0.50),
                    (0.85, 0.50),  # 4-7
                    (0.15, 0.75),
                    (0.38, 0.75),
                    (0.62, 0.75),
                    (0.85, 0.75),  # 8-11
                )

                if photo_count < 0 or photo_count > 11:
                    self.log_info(f"计算出的索引 {photo_count} 越界！强制安全到 11")
                    photo_count = 11

                target_target = photo_grid_locations[photo_count]
                self.operate_click(*target_target)
                self.sleep(1.14)
                # 点击物理删除确认
                self.operate_click(0.89, 0.94, action_name="del_photo")
                # 账本同步扣减：物理删一张，内存账本减一张
                current_total -= 1
                self.log_info(f" [{i + 1}/{number}]：删去1张照片，当前剩 {current_total} 张待删除")
                self.sleep(2.56)

        else:
            take_photo_actions = ["phone_third", "phone_self", "uav_third", "uav_first"]

            def take_photo(target_action="phone_third"):
                if target_action == "phone_third":
                    self.log_info("使用手机拍照：第三人称")
                elif target_action == "phone_self":
                    self.operate_click(0.84, 0.05)
                    self.log_info("使用手机拍照：自拍模式")
                    self.sleep(1.14)
                elif target_action in ["uav_third", "uav_first"]:
                    self.operate_click(0.895, 0.05)
                    self.sleep(1.14)
                    if target_action == "uav_first":
                        self.operate_click(0.89, 0.05)
                        self.log_info("使用无人机拍照：第一人称")
                        self.sleep(1.14)
                    else:
                        self.log_info("使用无人机拍照：第三人称")
                else:
                    self.log_info("使用手机拍照：第三人称")

            for i in range(number):
                if not self.enabled:
                    return False
                move_actions = ["w", "a", "s", "d", None]
                current_move_action = random.choice(move_actions)
                if action == "take_photo":
                    current_take_photo_action = random.choice(take_photo_actions)
                else:
                    current_take_photo_action = action
                if current_take_photo_action:
                    take_photo(target_action=current_take_photo_action)
                if current_move_action:
                    move_time = round(random.uniform(0.1, 1.0), 2)
                    self.send_key(current_move_action, down_time=move_time)
                self.log_info(f"正在拍摄第 {i + 1}张照片...")
                # 点击物理快门
                self.sleep(1.14)
                self.send_key("f", down_time=0.15)
                self.sleep(1.14)
                self.send_key("esc", down_time=0.15)
                self.sleep(1.14)
                if current_take_photo_action != "phone_third":
                    self.send_key("esc", down_time=0.15)
                    self.sleep(1.14)
            self.sleep(1.14)
            self.log_info("照片拍摄完毕，进入相册核对总数...")
            self.operate_click(0.035, 0.94)

            self.sleep(1.14)

        # 刷新最终总数
        self.get_gallery_total()
        self.sleep(1.14)
        return True

    # 获取相册相片数
    def get_gallery_total(self):
        gallery_total = self.find_area(area="gallery_total", action="get_text")
        photo_total = 1  # 安全默认值

        # 如果 OCR 没拿到任何东西
        if not gallery_total:
            self.log_info("[匹配失败] 未能找到相册相片数，启用安全值 1 张")
            self.gallery_total_count = photo_total
            return photo_total

        # 全文聚合
        full_ocr_text = "_".join(
            [str(node.name).strip() for node in gallery_total if hasattr(node, "name")]
        )
        self.log_info(f"原始OCR文本: '{full_ocr_text}'")

        match_prefer = self._RE_ALBUM_PREFER.search(full_ocr_text)
        match_backup = self._RE_ALBUM_BACKUP.search(full_ocr_text)
        match_last_resort = self._RE_ALBUM_LAST_RESORT.search(full_ocr_text)

        # 动态对齐
        HISTORY_KEYWORDS = ["史", "记录", "記錄", "istor", "erlauf", "стория"]
        if match_prefer:
            photo_total = int(match_prefer.group(1))
            self.log_info(f"[精准匹配] 相册相片数: {photo_total}")
        elif match_backup and any(kw in full_ocr_text for kw in HISTORY_KEYWORDS):
            photo_total = int(match_backup.group(1))
            self.log_info(f"[精准匹配] 相册相片数: {photo_total}")
        elif match_last_resort:
            photo_total = int(match_last_resort.group(1))
            self.log_info(f"[模糊匹配] 相册相片数: {photo_total} (原始文本: '{full_ocr_text}')")
        else:
            self.log_info(
                f"[匹配失败] 未能找到相册相片数，启用安全值 1 张，ocr结果为 '{full_ocr_text}'"
            )

        # 返回
        self.gallery_total_count = photo_total
        return photo_total

    # ==========================================
    # 通用工具模块
    # ==========================================

    # 打开手机模块
    def open_phone(self):
        self.wait_until(
            lambda: self.find_area(area="bagel_icon"),
            pre_action=lambda: self.send_key("esc", interval=3.14),
            time_out=30,
            raise_if_not_found=True,
        )
        self.log_info("已打开手机")

    # 进入功能模块
    def enter_app(self, app="bagel"):
        if app == "bagel":
            btn_bagel = self.find_area(area="bagel_icon", action="click")
            self.wait_until(
                lambda: not self.find_area(area="bagel_icon"),
                pre_action=lambda: self.operate_click(btn_bagel, interval=3.14),
                time_out=30,
                raise_if_not_found=True,
            )
        elif app == "camera":
            self.wait_until(
                lambda: not self.find_area(area="bagel_icon"),
                pre_action=lambda: self.operate_click(0.75, 0.875, interval=3.14),
                time_out=30,
                raise_if_not_found=True,
            )
        self.log_info(f"已打开{app}")

    # 区域找寻模块
    def find_area(self, area="reply_area", action=None):
        text_area = []
        # OCR区域的别名和坐标
        configs = {
            "bagel_icon": ((0.71, 0.37, 0.96, 0.80),),
            "gallery_total": ((0.03, 0.12, 0.14, 0.16),),
            "sort_menu_area": ((0.18, 0.10, 0.30, 0.20),),
            "sort_menu_area_done": ((0.18, 0.10, 0.30, 0.20), "sort_menu_select"),
            "sort_menu_list": ((0.18, 0.20, 0.30, 0.50), "sort_menu_area"),
            "sort_menu_select": ((0.18, 0.20, 0.30, 0.50),),
            "reply_area": ((0.70, 0.88, 0.95, 0.93),),
            "post_title": ((0.71, 0.20, 0.98, 0.26),),
            "poster_name": ((0.75, 0.13, 0.88, 0.20),),
            "post_enter_area": ((0.035, 0.89, 0.10, 0.99), "post_text"),
            "post_check_area": ((0.02, 0.08, 0.20, 0.16),),
            "post_photo_zone_area": ((0.10, 0.40, 0.60, 0.55),),
            "post_photo_confirm": ((0.825, 0.875, 0.95, 0.92), "confirm"),
            "post_title_area": ((0.71, 0.18, 0.92, 0.25),),
            "post_content_area": ((0.70, 0.35, 0.96, 0.45),),
            "post_confirm_area": ((0.86, 0.87, 0.97, 0.92), "post_text"),
        }
        if area not in configs:
            return None
        config_item = configs[area]
        ocr_area = config_item[0]  # 第一个元素必然是坐标元组

        if len(config_item) > 1:
            i18n_key = config_item[1]
        else:
            i18n_key = area

        # 若指定了 action = "click"，则采用 wait_ocr，否则采用 ocr 即可
        if action == "click":
            match_regex = re.compile(self.bagel_ocr[i18n_key])
            text_area = self.wait_ocr(
                *ocr_area, match=match_regex, time_out=30, raise_if_not_found=True
            )
        elif action == "get_text":
            text_area = self.ocr(*ocr_area)
        else:
            match_regex = re.compile(self.bagel_ocr[i18n_key])
            text_area = self.ocr(*ocr_area, match=match_regex)
        return text_area

    # 字数审查模块
    def text_length(self, text, max_len=25):
        """
        将回复内容智能控制在指定字数内，优先按标点截断保持语意完整
        """

        # 如果本身就没超限，直接放行
        if len(text) <= max_len:
            return text

        self.log_info(f"VLM 返回文本过长({len(text)}字)，触发25字硬限制截断流: '{text}'")

        # 定义常见的断句标点符号
        punctuations = ["，", "。", "！", "？", "；", "~", ",", ".", "!", "?", ";"]
        # 从第 max_len 个字符开始，逆向（往左）查找标点符号
        for i in range(max_len - 1, -1, -1):
            if text[i] in punctuations:
                # 最近的标点！截取到该标点（包含标点本身）
                trimmed_text = text[: i + 1]
                # 再次确保万无一失（正常情况下这里必然 <= max_len）
                if len(trimmed_text) <= max_len:
                    return trimmed_text

        # 兜底：如果前半句长达25个字里连一个标点都没有，被迫执行硬切断
        return text[: max_len - 1] + "…"

    # 截图获取模块
    def get_frame_by_ratio(self, x_min_ratio, y_min_ratio, x_max_ratio, y_max_ratio):
        """
        强制刷新并获取最新屏幕帧，然后按照屏幕比例进行裁切
        """
        new_frame = self.next_frame()
        if new_frame is None:
            self.log_error("无法获取新屏幕帧，比例裁切失败")
            return None

        height, width = new_frame.shape[:2]

        x_min = int(x_min_ratio * width)
        y_min = int(y_min_ratio * height)
        x_max = int(x_max_ratio * width)
        y_max = int(y_max_ratio * height)

        return new_frame[y_min:y_max, x_min:x_max]

    # 回复生成模块
    def generate_reply_content(self, title_text="帖子", author_name="呗主"):
        """生成回复内容（含降级机制与动态名字拼接）"""
        temp_img_path = ""
        cropped_frame = self.get_frame_by_ratio(0.015, 0.14, 0.98, 0.82)
        if cropped_frame is not None:
            # 将 NumPy 矩阵保存为本地临时图片
            # 如果大模型认出来的颜色很怪，说明截图框架出来的是 RGB，而 OpenCV 默认写出是 BGR
            # 此时可以用这行转换颜色：cropped_frame = cv2.cvtColor(cropped_frame, cv2.COLOR_RGB2BGR)

            temp_img_path = "vlm_input_temp.jpg"
            cv2.imwrite(temp_img_path, cropped_frame)
        else:
            temp_img_path = False

        # 如果配置了大模型，图片存在，优先走大模型
        if temp_img_path and self.config.get(self.CONF_MODEL, False):
            try:
                reply_prompt = self.config.get(
                    self.CONF_PROMPT_REPLY,
                    self.model_prompt["REPLY"],
                )
                model_reply = self.get_vlm_response(
                    reply_prompt, temp_img_path, post_title=title_text, author=author_name
                )
                self.log_info(f"模型生成 | 为帖子【{title_text}】生成回复: '{model_reply}'")
                return model_reply
            except Exception as e:
                self.log_info(f"VLM不可用({e})，降级到本地词库...")

        # 模型生成不可用时，使用本地词库随机回复
        base_reply = random.choice(self.preset_replies)

        # 40% 概率用对方昵称替换通称
        if author_name and author_name != "呗主" and random.random() < 0.4:
            base_reply = base_reply.replace("呗主", author_name).replace("博主", author_name)
        self.log_info(f"本地词库 | 为帖子【{title_text}】随机回复: '{base_reply}'")
        return base_reply

    # 贴文生成模块
    def generate_post_content(self, generate_type="title"):
        """生成发帖内容（含降级机制）"""
        temp_img_path = ""
        action = ""
        cropped_frame = None
        if generate_type == "title":
            action = "发帖标题"
            cropped_frame = self.get_frame_by_ratio(0.015, 0.15, 0.685, 0.82)
        else:
            action = "发帖文案"
            cropped_frame = self.get_frame_by_ratio(0.015, 0.10, 0.980, 0.82)
        if cropped_frame is not None:
            # 将 NumPy 矩阵保存为本地临时图片
            # 如果大模型认出来的颜色很怪，说明截图框架出来的是 RGB，而 OpenCV 默认写出是 BGR
            # 此时可以用这行转换颜色：cropped_frame = cv2.cvtColor(cropped_frame, cv2.COLOR_RGB2BGR)
            temp_img_path = "vlm_input_temp.jpg"
            cv2.imwrite(temp_img_path, cropped_frame)
        else:
            temp_img_path = False
        # 如果配置了大模型，图片存在，优先走大模型
        if temp_img_path and self.config.get(self.CONF_MODEL, False):
            try:
                post_prompt = ""
                if generate_type == "title":
                    post_prompt = self.config.get(
                        self.CONF_PROMPT_POST_TITLE,
                        self.model_prompt["POST_TITLE"],
                    )
                else:
                    post_prompt = self.config.get(
                        self.CONF_PROMPT_POST_CONTENT,
                        self.model_prompt["POST_CONTENT"],
                    )
                model_post = self.get_vlm_response(post_prompt, temp_img_path)
                self.log_info(f"模型生成 | 为所选图片生成{action}: '{model_post}'")
                if generate_type == "title":
                    self.nowview_post = model_post
                return model_post
            except Exception as e:
                self.log_info(f"VLM不可用({e})，降级到本地词库...")

        # 模型生成不可用时，使用本地词库随机选取
        base_post = random.choice(self.preset_posts)
        self.log_info(f"本地词库 | 为所选图片随机选取{action}: '{base_post}'")
        return base_post

    # 模型调用模块
    def get_vlm_response(self, prompt, post_img_path, post_title=None, author=None):
        """
        使用原生 requests 调用 VLM 模型（支持从 /v1/models 自动抓取真名，完美兼容 llama.cpp/LM Studio）
        """
        base_url = self.config.get(self.CONF_MODEL_URL, "http://127.0.0.1:1234").rstrip("/")
        api_key = self.config.get(self.CONF_MODEL_API, "")
        if api_key and len(api_key) > 7:
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        else:
            headers = {
                "Content-Type": "application/json",
            }
        # ==========================================
        # 动态从 /v1/models 探测当前模型名
        # ==========================================
        model_name = "local-model"  # 缺省兜底值
        preferred_model = self.config.get(self.CONF_MODEL_NAME, "qwen/qwen3-vl-4b")  # 指定主导模型
        models_url = f"{base_url}/v1/models"
        models_response = requests.get(models_url, headers=headers, timeout=3)
        if models_response.status_code == 200:
            models_data = models_response.json()
            if "data" in models_data and len(models_data["data"]) > 0:
                # 提取出当前后端所有可用的模型 ID 列表
                available_model_ids = [m["id"] for m in models_data["data"]]
                # 策略 1：检查我们最爱的 qwen/qwen3-vl-4b 在不在里面
                if preferred_model in available_model_ids:
                    model_name = preferred_model
                    self.log_info(f"成功加载指定模型: '{model_name}'")
                # 指定的模型不在，找其它视觉模型代替
                else:
                    vl_models = [mid for mid in available_model_ids if "-vl" in mid.lower()]
                    if vl_models:
                        model_name = vl_models[0]
                        self.log_info(f"未找到指定模型，加载其他视觉模型: '{model_name}'")
                    # 没有视觉模型，抛出异常降级到本地词库
                    else:
                        raise RuntimeError("未找到指定模型和其他视觉模型")

        # ==========================================
        # 后续的标准 Vision 请求逻辑
        # ==========================================
        api_url = f"{base_url}/v1/chat/completions"

        final_prompt = prompt
        if post_title or author:
            final_prompt += "\n\n【目标帖子信息】"
            if post_title:
                final_prompt += f"\n标题: {post_title}"
            if author:
                final_prompt += f"\n发帖者: {author}"

        # 转图片 Base64
        with open(post_img_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode("utf-8")

        # 组装完整的 Payload
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": final_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                        },
                    ],
                }
            ],
            "temperature": 0.7,
            "max_tokens": 150,
        }

        self.log_info("正在向后端发送推理请求...")
        response = requests.post(api_url, headers=headers, data=json.dumps(payload), timeout=30)

        if response.status_code == 200:
            model_reply = response.json()["choices"][0]["message"]["content"].strip()
            if not model_reply:
                raise RuntimeError(f"VLM 返回内容异常, 详情: {response.text}")
            model_reply = self.text_length(model_reply, max_len=25)
            return model_reply
        else:
            raise RuntimeError(
                f"VLM 推理失败，HTTP 状态码: {response.status_code}, 详情: {response.text}"
            )