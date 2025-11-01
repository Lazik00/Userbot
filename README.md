# Userbot

Этот репозиторий содержит простой Python-проект (userbot).

Содержимое:
- `main.py` — основная точка входа.
- `prompt.py` — вспомогательные утилиты/данные для проекта.
- `session_name.session`, `session_name.session-journal` — файлы сессии (НЕ включать в репозиторий).

Подготовка и рекомендации для Git (Windows `cmd.exe`):

1) Инициализировать репозиторий (если ещё не инициализирован):

```cmd
cd C:\Users\Laziz\Desktop\userbot
git init
```

2) Создать виртуальное окружение и установить зависимости (если есть `requirements.txt`):

```cmd
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

3) Создать `.gitignore` (в репозитории уже есть) — оно исключает временные файлы, сессии и окружения.

4) Добавить файлы и сделать первый коммит:

```cmd
git add .
git commit -m "Initial commit: add project files and .gitignore"
```

5) Подключить удалённый репозиторий и отправить (пример):

```cmd
git remote add origin https://github.com/USERNAME/REPO.git
git branch -M main
git push -u origin main
```

Примечания:
- Файлы `*.session` и `*.session-journal` содержат чувствительные токены/сессии. Они добавлены в `.gitignore` — убедитесь, что вы не закоммитили их ранее (если уже закоммитили, удалите из репозитория командой `git rm --cached <file>`).
- Рекомендуется хранить секреты в переменных окружения или в `.env` (который тоже в `.gitignore`).

Если хотите, могу: добавить `requirements.txt`, настроить `pyproject.toml`, или проверить код в `main.py` и `prompt.py` на ошибки/стиль. Напишите, что делаем дальше.
