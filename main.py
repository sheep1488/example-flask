import discord
from discord.ext import commands, tasks
import random
import sqlite3
import asyncio
import pytz
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from discord.ui import Button, View
import json


engine = create_engine('sqlite:///user_levels.db')
Session = sessionmaker(bind=engine)
from sqlalchemy.orm import declarative_base
Base = declarative_base()

class UserLevels(Base):
    __tablename__ = 'user_levels'

    user_id = Column(Integer, primary_key=True)
    level = Column(Integer, default=0)

Base.metadata.create_all(engine)
attack_channel_id = 1101123263628849266

monster_created = False
monster_health = 0
monster_level = 0
monster_created_time = None

last_attack_times = {}

def reset_monster():
    global monster_created
    global monster_health
    global monster_level
    global monster_created_time
    monster_created = False
    monster_health = 0
    monster_level = 0
    monster_created_time = None

def can_attack_monster(ctx):
    return (
        ctx.channel.id == attack_channel_id
        and monster_created
        and (datetime.now() - monster_created_time).seconds < 5 * 60
    )

# Создаем одно соединение с базой данных и курсор
conn = sqlite3.connect('economy.db')
cursor = conn.cursor()

# Создаем таблицу пользователей в базе данных, если ее нет
def create_users_table():
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            balance INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            inventory TEXT,
            xp INTEGER DEFAULT 0,
            bucks INTEGER DEFAULT 0,
            last_daily_reward TEXT
        )'''
    )
    conn.commit()

# Добавляем новую колонку, если ее нет
def add_last_reward_column():
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN last_daily_reward TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fishing (
            user_id TEXT PRIMARY KEY,
            last_used TEXT
        )
    """)
    conn.commit()


create_users_table()

def create_fishing_table():
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS fishing (
            user_id TEXT PRIMARY KEY,
            last_used TEXT
        )'''
    )
    conn.commit()

if __name__ == "__main__":
    create_users_table()
    create_fishing_table()    

def create_marriages_table():
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS marriages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user1_id INTEGER,
            user2_id INTEGER,
            FOREIGN KEY (user1_id) REFERENCES users(user_id),
            FOREIGN KEY (user2_id) REFERENCES users(user_id)
        )'''
    )
    conn.commit()

def marry_users(user1_id, user2_id):
    cursor.execute('INSERT INTO marriages (user1_id, user2_id) VALUES (?, ?)', (user1_id, user2_id))
    conn.commit()

def is_married(user_id):
    cursor.execute('SELECT * FROM marriages WHERE user1_id=? OR user2_id=?', (user_id, user_id))
    result = cursor.fetchone()
    return result is not None and (result[1] == user_id or result[2] == user_id)

# Создаем таблицу товаров в базе данных
def create_marketplace_table():
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS marketplace (
            item_id INTEGER PRIMARY KEY,
            item_name TEXT,
            price INTEGER,
            seller_id TEXT,
            FOREIGN KEY (item_id) REFERENCES items(item_id),
            FOREIGN KEY (seller_id) REFERENCES users(user_id)
        )'''
    )
    conn.commit()

def init_db():
    connection = sqlite3.connect("users.db")
    cursor = connection.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY, level INTEGER, messages_sent INTEGER, hunger INTEGER)''')
    connection.commit()
    connection.close()

init_db()

def get_user_data(user_id):
    connection = sqlite3.connect("users.db")
    cursor = connection.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user_data = cursor.fetchone()
    connection.close()

    if user_data:
        return {'level': user_data[1], 'messages_sent': user_data[2], 'hunger': user_data[3]}
    else:
        set_user_data(user_id, 1, 0, 100)
        return {'level': 1, 'messages_sent': 0, 'hunger': 100}

def set_user_data(user_id, level, messages_sent, hunger):
    connection = sqlite3.connect("users.db")
    cursor = connection.cursor()
    cursor.execute("REPLACE INTO users (user_id, level, messages_sent, hunger) VALUES (?, ?, ?, ?)",
                   (user_id, level, messages_sent, hunger))
    connection.commit()
    connection.close()

    cursor.execute('''CREATE TABLE IF NOT EXISTS inventory
                     (user_id INTEGER, berry_name TEXT, quantity INTEGER)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS berries
                     (berry_name TEXT PRIMARY KEY, hunger_value INTEGER)''')

    # Добавим несколько видов ягод в таблицу berries
    cursor.executemany('''INSERT OR IGNORE INTO berries (berry_name, hunger_value) VALUES (?, ?)''', [
        ("MagicBlueberry", 10),
        ("GoldenRaspberry", 20),
        ("MysticStrawberry", 5)
    ])

    connection.commit()
    connection.close()

# Вызываем функции для создания таблиц в базе данных
create_marketplace_table()
create_marriages_table()

def get_user_inventory(user_id):
    cursor.execute('SELECT inventory FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result is not None:
        return result[0]
    else:
        return ""

def get_user_balance(user_id):
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result is not None:
        return result[0]
    else:
        return 0

def subtract_coins(user_id, amount):
    cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (amount, user_id))
    conn.commit()

def add_coins(user_id, amount):
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()

def create_inventory_embed(username, inventory):
    embed = discord.Embed(title=f"Инвентарь {username}", description=f"Ваш инвентарь: {inventory}", color=0xFFD700)
    return embed

market_items = {
    'Удочка мастера': 7000,
    'Удочка новичка': 200,
}

# Создаем объект Bot с необходимыми настройками
timezone = pytz.timezone('Europe/Moscow')
intents = discord.Intents.all()
intents.members = True
intents.messages = True
bot = commands.Bot(command_prefix='!', intents=intents)

def update_balances():
    cursor.execute('SELECT user1_id, user2_id FROM marriages')
    results = cursor.fetchall()
    for result in results:
        user1_id, user2_id = result[0], result[1]
        give_coins(user1_id, 1000)
        give_coins(user2_id, 1000)

def give_coins(user_id, amount):
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()

@bot.event
async def on_ready():
    # Запускаем цикл, который будет обновлять балансы каждую неделю
    while True:
        update_balances()
        await asyncio.sleep(7 * 24 * 60 * 60)  # 1 неделя

@bot.event
async def on_member_join(member):
    role_id = 1097872882585059409 
    role = discord.utils.get(member.guild.roles, id=role_id)
    await member.add_roles(role)

wait_time = timedelta(minutes=15)
last_used = {}

@bot.command()
async def предложить_брак(ctx, member: discord.Member):
    if member == ctx.author:
        await ctx.send("Вы не можете себе предложить.")
        return

    if is_married(ctx.author.id):
        await ctx.send("Вы уже состоите в браке.")
        return

    if is_married(member.id):
        await ctx.send(f"{member.display_name} уже состоит в браке.")
        return

    author_gender = "Мужской" if "Мужской" in [role.name for role in ctx.author.roles] else "Женский"
    member_gender = "Мужской" if "Мужской" in [role.name for role in member.roles] else "Женский"

    if author_gender == member_gender:
        await ctx.send("Брак можно заключить только между участниками разных полов.")
        return

    proposal_message = f"{ctx.author.display_name} предлагает вам брак. Принимаете? (Да/Нет)"
    proposal = await member.send(proposal_message)

    try:
        response = await bot.wait_for("message", timeout=60, check=lambda m: m.author == member)
    except asyncio.TimeoutError:
        await ctx.send(f"{member.display_name} не принял ваше предложение.")
        return

    if response.content.lower() == "да":
        marry_users(ctx.author.id, member.id)
        await ctx.send(f"Поздравляем! {ctx.author.display_name} и {member.display_name} теперь состоят в браке.")
    elif response.content.lower() == "нет":
        await ctx.send(f"{member.display_name} отклонил ваше предложение.")
    else:
        await ctx.send("Некорректный ответ. Пожалуйста, введите 'Да' или 'Нет'.")



@bot.command()
async def развод(ctx):
    user_id = ctx.author.id
    if not is_married(user_id):
        await ctx.send("Вы не состоите в браке.")
        return

    cursor.execute('SELECT user1_id, user2_id FROM marriages WHERE user1_id=? OR user2_id=?',
                   (user_id, user_id))
    result = cursor.fetchone()
    user1_id, user2_id = result[0], result[1]

    partner_id = user1_id if user1_id != user_id else user2_id
    partner = await bot.fetch_user(partner_id)

    cursor.execute('DELETE FROM marriages WHERE user1_id=? OR user2_id=?', (user_id, user_id))
    conn.commit()

    await ctx.send(f"Вы развелись с {partner.mention}.")
@bot.command()
async def мой_брак(ctx):
    if not is_married(ctx.author.id):
        await ctx.send("Вы не состоите в браке.")
        return

    cursor.execute('SELECT user1_id, user2_id FROM marriages WHERE user1_id=? OR user2_id=?',
                   (ctx.author.id, ctx.author.id))
    result = cursor.fetchone()
    user1_id, user2_id = result[0], result[1]

    partner_id = user1_id if user1_id != ctx.author.id else user2_id
    partner = await bot.fetch_user(partner_id)

    await ctx.send(f"Вы состоите в браке с {partner.mention}.")

@bot.command()
async def купить(ctx, *, item_name):
    user_id = str(ctx.author.id)
    cursor.execute(f"SELECT balance FROM users WHERE user_id='{user_id}'")
    balance = cursor.fetchone()[0]
    if item_name not in market_items:
        await ctx.send(f"{ctx.author.mention}, этого товара нет в магазине.")
    elif balance < market_items[item_name]:
        await ctx.send(f"{ctx.author.mention}, у вас недостаточно прусов для покупки этого товара.")
    else:
        # Вычитаем цену товара из баланса пользователя
        new_balance = balance - market_items[item_name]
        cursor.execute(f"UPDATE users SET balance={new_balance} WHERE user_id='{user_id}'")
        # Добавляем товар в инвентарь пользователя
        cursor.execute(f"SELECT inventory FROM users WHERE user_id='{user_id}'")
        inventory = cursor.fetchone()[0]
        if inventory:
            inventory = inventory + f", {item_name}"
        else:
            inventory = item_name
        cursor.execute(f"UPDATE users SET inventory='{inventory}' WHERE user_id='{user_id}'")
        # Добавляем товар в базу данных магазина
        cursor.execute(f"SELECT COUNT(*) FROM marketplace WHERE seller_id='{user_id}'")
        num_items = cursor.fetchone()[0]
        cursor.execute(f"INSERT INTO marketplace (item_id, item_name, price, seller_id) VALUES ({num_items+1}, '{item_name}', {market_items[item_name]}, '{user_id}')")
        conn.commit()
        await ctx.send(f"{ctx.author.mention}, товар '{item_name}' успешно куплен за {market_items[item_name]} прусов.")


@bot.command()
async def передать_вещь(ctx, member: discord.Member, *, item_name):
    # Получаем ID отправителя и получателя
    sender_id = str(ctx.author.id)
    receiver_id = str(member.id)

    # Проверяем, что товар существует в инвентаре отправителя
    cursor.execute(f"SELECT inventory FROM users WHERE user_id='{sender_id}'")
    inventory = cursor.fetchone()[0]
    if item_name not in inventory:
        await ctx.send(f"{ctx.author.mention}, у вас нет такого товара в инвентаре.")
        return

    # Проверяем, что отправитель и получатель разные пользователи
    if sender_id == receiver_id:
        await ctx.send(f"{ctx.author.mention}, нельзя передать товар самому себе.")
        return

    # Проверяем, что получатель существует в базе данных
    cursor.execute(f"SELECT user_id FROM users WHERE user_id='{receiver_id}'")
    if not cursor.fetchone():
        await ctx.send(f"{ctx.author.mention}, этот пользователь не зарегистрирован.")
        return

    # Перемещаем товар из инвентаря отправителя в инвентарь получателя
    cursor.execute(f"SELECT inventory FROM users WHERE user_id='{receiver_id}'")
    receiver_inventory = cursor.fetchone()[0]
    if receiver_inventory:
        receiver_inventory = receiver_inventory + f", {item_name}"
    else:
        receiver_inventory = item_name
    cursor.execute(f"UPDATE users SET inventory='{receiver_inventory}' WHERE user_id='{receiver_id}'")
    inventory = inventory.replace(item_name, '').replace(', ,', ',').strip(',')
    cursor.execute(f"UPDATE users SET inventory='{inventory}' WHERE user_id='{sender_id}'")

    conn.commit()
    await ctx.send(f"{ctx.author.mention}, вы успешно передали товар '{item_name}' пользователю {member.mention}.")

@bot.command()
async def инвентарь(ctx):
    user_id = str(ctx.author.id)
    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user_data = cursor.fetchone()
    if user_data is None:
        cursor.execute("INSERT INTO users (user_id, balance, level, inventory, xp) VALUES (?, ?, ?, ?, ?)", (user_id, 0, 1, '{}', 0))
        conn.commit()
        inventory = {}
    else:
        inventory_str = user_data[3]
        if inventory_str:
            try:
                inventory = json.loads(inventory_str)
            except json.JSONDecodeError:
                inventory = {}
        else:
            inventory = {}
    conn.close()

    embed = discord.Embed(title=f"Инвентарь {ctx.author.display_name}", color=0xFFD700)
    embed.set_thumbnail(url=ctx.author.display_avatar.url)

    if inventory:
        inventory_items = [f"{item}: {quantity}" for item, quantity in inventory.items()]
        inventory_text = "\n".join(inventory_items)
        embed.add_field(name="Ваш инвентарь", value=inventory_text)
    else:
        embed.add_field(name="Ваш инвентарь", value="Инвентарь пуст")

    await ctx.author.send(embed=embed)

last_used = {}

class RubButtonView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.timeout = 60 * 4  # 4 минуты в секундах

    async def on_timeout(self):
        await self.message.delete()

    @discord.ui.button(label='Рубить', style=discord.ButtonStyle.primary, custom_id='rub_button')
    async def button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.rub(interaction)

    async def start(self, ctx: commands.Context):
        view = self
        self.message = await ctx.send("Нажмите кнопку", view=view)
        while True:
            await asyncio.sleep(120)  # Ожидание 4 минуты
            await self.message.delete()
            self.message = await ctx.send("Нажмите кнопку ниже, чтобы продолжить рубить!", view=view)

    async def rub(self, interaction):
        ctx = interaction.user

        if interaction.channel_id != 1114623361130168371:
            await interaction.channel.send("Здесь нельзя рубить, рубить можно только в лесу! (Купите локацию лес в текстовом канале - #локации).")
            return

        user_id = str(ctx.id)

        # Отладка
        print(f"Last used for {user_id}: {last_used.get(user_id)}")

        if user_id in last_used:
            time_since_last_use = datetime.now() - last_used[user_id]
            if time_since_last_use < timedelta(minutes=4):
                await interaction.followup.send(f'Можно рубить раз в 4 минуты, а ты поторопился. Подожди еще {4 - time_since_last_use.seconds // 60} мин.', ephemeral=True)
                return

        axes = {"Обычный топор": 10, "Стальной топор": 20, "Алмазный топор": 30}
        chosen_axe = "Обычный топор"
        max_amount = axes[chosen_axe]

        wood_amount = random.randint(20, 40)

        conn = sqlite3.connect('economy.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        user_data = cursor.fetchone()
        if user_data is None:
            cursor.execute("INSERT INTO users (user_id, balance, level, inventory, xp) VALUES (?, ?, ?, ?, ?)", (user_id, wood_amount, 1, '', 0))
        else:
            current_balance = user_data[1]
            new_balance = current_balance + wood_amount
            cursor.execute("UPDATE users SET balance=? WHERE user_id=?", (new_balance, user_id))
        
        conn.commit()
        conn.close()
        
        embed = discord.Embed(title="Результат рубки дерева", description=f"{ctx.mention}, вы срубили {wood_amount} дерева и заработали {wood_amount}", color=discord.Color.green())
        await interaction.followup.send(embed=embed, ephemeral=True)     
        last_used[user_id] = datetime.now()

@bot.command()
async def рубить(ctx):
    view = RubButtonView()
    await view.start(ctx)
    
@bot.command()
async def купить_шахта(ctx):
    user_id = str(ctx.author.id)
    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user_data = cursor.fetchone()
    if user_data is None:
        cursor.execute("INSERT INTO users (user_id, balance, level, inventory, xp) VALUES (?, ?, ?, ?, ?)", (user_id, 0, 1, '', 0))
        conn.commit()
        balance = 0
    else:
        balance = user_data[1]
    conn.close()

    if balance < 30000:
        await ctx.send(f"{ctx.author.mention}, у вас недостаточно просов для покупки геолокации шахта.")
        return

    member = ctx.author
    role = discord.utils.get(ctx.guild.roles, name="шахтер")
    if role in member.roles:
        await ctx.send(f"{ctx.author.mention}, зачем вам 2 шахты?).")
        return

    await member.add_roles(role)
    new_balance = balance - 30000
    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance=? WHERE user_id=?", (new_balance, user_id,))
    conn.commit()
    conn.close()

    await ctx.send(f"{ctx.author.mention}, вы успешно купили геолокацию шахта.")

@bot.command()
async def купить_лес(ctx):
    user_id = str(ctx.author.id)
    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user_data = cursor.fetchone()
    if user_data is None:
        cursor.execute("INSERT INTO users (user_id, balance, level, inventory, xp) VALUES (?, ?, ?, ?, ?)", (user_id, 0, 1, '', 0))
        conn.commit()
        balance = 0
    else:
        balance = user_data[1]
    conn.close()

    if balance < 10000:
        await ctx.send(f"{ctx.author.mention}, у вас недостаточно просов для покупки геолокации лес.")
        return

    member = ctx.author
    role = discord.utils.get(ctx.guild.roles, name="лесоруб")
    if role in member.roles:
        await ctx.send(f"{ctx.author.mention}, зачем вам 2 лес?).")
        return

    await member.add_roles(role)
    new_balance = balance - 10000
    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance=? WHERE user_id=?", (new_balance, user_id,))
    conn.commit()
    conn.close()

    await ctx.send(f"{ctx.author.mention}, вы успешно купили геолокацию лес.")

@bot.command()
async def изменить_баланс(ctx, member: discord.Member, amount: int):
    if not ctx.guild:
        await ctx.send("Команду `изменить_баксы` можно использовать только на сервере.")
        return
    """Команда для изменения баланса пользователя."""
    user_id = str(member.id)
    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user_data = cursor.fetchone()
    if user_data is None:
        await ctx.send("Указанный пользователь не зарегистрирован в экономике.")
    else:
        new_balance = user_data[1] + amount
        cursor.execute("UPDATE users SET balance=? WHERE user_id=?", (new_balance, user_id))
        conn.commit()
        await ctx.send(f"Баланс пользователя {member.mention} изменен на {amount}.")
    conn.close()

class FishingView(discord.ui.View):
    def __init__(self):
        super().__init__()

        self.create_button()

    def create_button(self):
        self.button = discord.ui.Button(style=discord.ButtonStyle.primary, label="Рыбалка")
        self.button.callback = self.button_callback
        self.add_item(self.button)

    async def button_callback(self, interaction: discord.Interaction):
        fish_list = ['Лосось', 'Карп', 'Окунь', 'Судак', 'Форель']
        caught_fish = random.choice(fish_list)
        user_id = str(interaction.user.id)
        conn = sqlite3.connect('economy.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        user_data = cursor.fetchone()

        if user_data is None:
            cursor.execute("INSERT INTO users (user_id, balance, level, inventory, xp) VALUES (?, ?, ?, ?, ?)",
                           (user_id, 0, 1, '', 0))
            conn.commit()
            balance = 0
            inventory = {}
        else:
            balance = user_data[1]
            inventory_str = user_data[3]
            inventory = dict(item.split(':') for item in inventory_str.split(',')) if inventory_str else {}

        last_used = {}

        # Получаем время последнего использования команды из базы данных
        cursor.execute("SELECT last_used FROM fishing WHERE user_id=?", (user_id,))
        last_used_data = cursor.fetchone()
        if last_used_data is not None:
            last_used[user_id] = datetime.fromisoformat(last_used_data[0])

        if user_id in last_used:
            time_since_last_use = datetime.utcnow() - last_used[user_id]
            if time_since_last_use < timedelta(minutes=3):
                await interaction.response.send_message(f'Вы устали от рыбалки, подождите еще {5 - time_since_last_use.seconds // 60} минут.', ephemeral=True)
                return

        role = discord.utils.get(interaction.user.roles, name="Рыбак")

        if role is not None:
            # Если у пользователя есть роль "Мастер рыбак", изменяем вероятности выпадения прусов
            chances = {
                "Любитель рыбак": 0.5,
                "Профессионал рыбак": 0.8
            }

            prus_count = 5

            for fish, fish_chance in chances.items():
                if random.random() < fish_chance:
                    balance += prus_count
                    if fish in inventory:
                        inventory[fish] += 1
                    else:
                        inventory[fish] = 1

            cursor.execute("UPDATE users SET balance=?, inventory=? WHERE user_id=?", (balance, ','.join([f'{fish}:{inventory.get(fish, 0)}' for fish in fish_list]), user_id))
            conn.commit()

            embed = discord.Embed(
                title='Рыбалка',
                description=f'Вы поймали рыбу {caught_fish} и получили {prus_count} прусов!',
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

            # Обновляем время последнего использования команды в базе данных
            last_used_time = datetime.utcnow().isoformat()
            cursor.execute("INSERT OR REPLACE INTO fishing (user_id, last_used) VALUES (?, ?)", (user_id, last_used_time))
            conn.commit()
            conn.close()

            # Отмечаем взаимодействие как отложенное, чтобы кнопка оставалась активной
            interaction.response.send_message()
        else:
            embed = discord.Embed(title='Рыбалка', description='У вас нет доступа к рыбалке!', color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
@bot.command()
async def рыбалка(ctx):
    view = FishingView()
    message = await ctx.send("Нажми на кнопку снизу чтобы начать рыбачить", view=view)

    while True:
        await asyncio.sleep(240)  # Ожидание 10 минут (600 секунд)

        # Удаление предыдущего сообщения
        await message.delete()

        # Создание нового сообщения с кнопкой
        view = FishingView()
        message = await ctx.send("Нажми на кнопку снизу чтобы начать рыбачить", view=view)

@bot.command()
async def передать_прусы(ctx, recipient: discord.Member, amount: int):
    author_id = str(ctx.author.id)
    recipient_id = str(recipient.id)
    if not isinstance(amount, int):
        await ctx.send("Пожалуйста, укажите количество прус целым числом.")
        return
    user_id = str(ctx.author.id)
    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    sender_data = cursor.fetchone()
    if sender_data is None:
        cursor.execute("INSERT INTO users (user_id, balance, level, inventory, xp) VALUES (?, ?, ?, ?, ?)", (user_id, 0, 1, '', 0))
        conn.commit()
        balance = 0
    else:
        balance = sender_data[1]
    if balance < amount:
        conn.close()
        await ctx.send("У вас недостаточно прусов для выполнения этой операции.")
        return
    cursor.execute("SELECT * FROM users WHERE user_id=?", (recipient_id,))
    recipient_data = cursor.fetchone()
    if recipient_data is None:
        cursor.execute("INSERT INTO users (user_id, balance, level, inventory, xp) VALUES (?, ?, ?, ?, ?)", (recipient_id, 0, 1, '', 0))
        recipient_data = (recipient_id, 0, 1, '', 0)
        conn.commit()
    cursor.execute("UPDATE users SET balance=? WHERE user_id=?", (sender_data[1] - amount, user_id))
    cursor.execute("UPDATE users SET balance=? WHERE user_id=?", (recipient_data[1] + amount, recipient_id))
    conn.commit()
    conn.close()
    embed = discord.Embed(title=f"Передача прусов", description=f"{ctx.author.display_name} передал {recipient.display_name} {amount} прусов🪙.", color=0xFFD700)
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)


import secrets
import requests
import urllib.parse

payment_amounts = {}
payment_codes = {}

payment_amounts = {}
payment_codes = {}

QIWI_TOKEN = "a206bf3c8f9336103ef9bc121807b5ba"
QIWI_PHONE_NUMBER = "+79242938322"

def check_qiwi_payment(token, phone_number, code):
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}"
    }
    url = f"https://edge.qiwi.com/payment-history/v2/persons/{phone_number}/payments?rows=10"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        payments = response.json()["data"]
        for payment in payments:
            if payment["comment"] and code in payment["comment"]:
                return payment["sum"]["amount"], payment["status"] == "SUCCESS"
    return None, False

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')

@bot.command(name='оплата_баксы')
async def payment(ctx):
    if ctx.guild:
        return  # Прерываем выполнение команды, если она была вызвана не в личных сообщениях.
    amount = 75
    phone = QIWI_PHONE_NUMBER
    payment_amounts[ctx.author.id] = amount
    code = secrets.token_hex(8)
    payment_codes[ctx.author.id] = code
    encoded_phone = urllib.parse.quote(phone, safe='')
    encoded_code = urllib.parse.quote(code, safe='')
    payment_url = f'https://qiwi.com/payment/form/99?extra%5B%27account%27%5D={encoded_phone}&amountInteger={amount}&amountFraction=0&extra%5B%27comment%27%5D={encoded_code}'
    embed = discord.Embed(title="Ссылка на оплату ", color=discord.Color.blue())
    embed.add_field(name=f'Сумма оплаты {amount}. Вот ваш код: {code}.', value=f"хорошей покупки", inline=False)
    embed.url = payment_url
    await ctx.send(embed=embed)
    await asyncio.sleep(5)  # 5 minutes delay for checking payment
    paid_amount, success = check_qiwi_payment(QIWI_TOKEN, QIWI_PHONE_NUMBER, code)
    if success and paid_amount == amount:
        cursor.execute("UPDATE users SET bucks = bucks + 100 WHERE user_id = ?", (str(ctx.author.id),))
        conn.commit()
        await ctx.send(f"{ctx.author.mention}, ваша оплата была успешно проведена! Вам было добавлено 100 баксов.")

@bot.command(name='баланс')
async def balance(ctx):
    user_id = str(ctx.author.id)
    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user_data = cursor.fetchone()
    if user_data is None:
        cursor.execute("INSERT INTO users (user_id, balance, level, inventory, xp, bucks) VALUES (?, ?, ?, ?, ?, ?)", (user_id, 0, 1, '', 0, 0))
        conn.commit()
        balance = 0
        bucks = 0
    else:
        balance = user_data[1]
        bucks = user_data[5]
    embed = discord.Embed(title=f"Баланс {ctx.author.display_name}", description=f"Ваш баланс: {balance} прусов🪙, {bucks} Баксов💵.", color=0xFFD700)
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    await ctx.author.send(embed=embed)

@bot.command(name='платеж')
async def check_payment(ctx, code: str = None):
    if ctx.guild:
        return
    if code is None:
        await ctx.send('Укажите код для проверки оплаты.')
    elif ctx.author.id in payment_codes and payment_codes[ctx.author.id] == code:
        amount, status = check_qiwi_payment(QIWI_TOKEN, QIWI_PHONE_NUMBER, code)
        if status:
            payment_amount = payment_amounts.get(ctx.author.id, 0)
            user_id = str(ctx.author.id)
            
            # Начисляем баксов
            cursor.execute("UPDATE users SET bucks = bucks + 100 WHERE user_id = ?", (user_id,))
            conn.commit()
            
            # Удаляем использованный код
            del payment_codes[ctx.author.id]
            
            await ctx.send(f'Платеж на сумму {amount} успешно проведен! Вам было начислено 100 баксов.')
        else:
            await ctx.send('Платеж не найден или не выполнен. Попробуйте еще раз.')
    else:
        await ctx.send('Указанный код не совпадает с предоставленным кодом для оплаты. Проверьте код!')

@bot.command(name='инструкция_оплата')
async def payment_instructions(ctx):
    embed = discord.Embed(title="Инструкция по оплате", color=discord.Color.blue())

    instructions = [
        "1) Заходим в личные сообщения с ботом.",
        "2) Вводим `!оплата_баксы` либо `!оплата_VIP`. Бот скидывает ссылку на Киви с уникальным кодом.",
        "3) Вводим данные в Киви и оплачиваем.",
        "4) После оплаты пишем `!платеж` и ваш уникальный код.",
        "5) Радуемся покупке!"
    ]

    for instruction in instructions:
        embed.add_field(name=instruction, value='\u200b', inline=False)

    await ctx.send(embed=embed)

FATIGUE_DELAY = 600
last_command_use = {}

class MyView(discord.ui.View):
    def __init__(self):
        super().__init__()

        # Создаем кнопку
        self.create_button()

    def create_button(self):
        # Создаем кнопку с меткой "Нажми меня!"
        self.button = Button(style=discord.ButtonStyle.primary, label="Копать")

        # Добавляем обработчик нажатия на кнопку
        self.button.callback = self.button_callback

        # Добавляем кнопку на View
        self.add_item(self.button)

    # Обработчик нажатия на кнопку
    async def button_callback(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("Команду `копать` можно использовать только на сервере.", ephemeral=True)
            return

        if interaction.channel.id != 1114623342398414878:
            await interaction.response.send_message("Здесь нельзя копать, копать можно только в шахте!", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        conn = sqlite3.connect('economy.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        user_data = cursor.fetchone()
        if user_data is None:
            cursor.execute("INSERT INTO users (user_id, balance, level, xp) VALUES (?, ?, ?, ?, ?)",
                           (user_id, 0, 1, '', 0))
            conn.commit()
            balance = 0
            inventory = {}
        else:
            balance = user_data[1]
        conn.close()

        # определяем переменную cooldowns, если её нет
        if 'cooldowns' not in globals():
            global cooldowns
            cooldowns = {}

        # проверяем, прошло ли достаточно времени с момента последнего использования команды
        last_cooldown = cooldowns.get(interaction.user.id)
        if last_cooldown is not None and datetime.now() < last_cooldown + timedelta(minutes=5):
            time_left = last_cooldown + timedelta(minutes=5) - datetime.now()
            await interaction.response.send_message(f"Вы устали. Пожалуйста, подождите ещё {time_left.seconds // 60} минут и {time_left.seconds % 60} секунд, чтобы использовать эту команду снова.", ephemeral=True)
            return

        # Определение диапазона заработка в зависимости от роли
        if "Мастер шахтёр" in [role.name for role in interaction.user.roles]:
            earnings = random.randint(120, 300)
        elif "Профессионал шахтёр" in [role.name for role in interaction.user.roles]:
            earnings = random.randint(600, 900)
        else:
            earnings = random.randint(80, 120)

        new_balance = balance + earnings
        conn = sqlite3.connect('economy.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance=? WHERE user_id=?", (new_balance, user_id))
        conn.commit()
        conn.close()

        # сохраняем время последнего использования команды
        cooldowns[interaction.user.id] = datetime.now()

        embed = discord.Embed(
            title="Вы успешно добыли руду!",
            description=f"Вы получили {earnings} прусов🪙.",
                color=0x00FF00
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.command()
async def копать(ctx):
    # Получаем предыдущее сообщение с кнопкой
    channel = ctx.channel
    message = await channel.fetch_message(ctx.message.id)

    # Удаляем предыдущее сообщение
    await message.delete()

    # Создаем экземпляр MyView и добавляем его в сообщение
    view = MyView()
    new_message = await ctx.send("Нажми на кнопку снизу чтобы начать копать", view=view)

    while True:
        await asyncio.sleep(120)  # Ожидание 10 минут (600 секунд)

        # Удаление предыдущего сообщения
        await new_message.delete()

        # Создание нового сообщения с кнопкой
        view = MyView()
        new_message = await ctx.send("Нажми на кнопку снизу чтобы начать копать", view=view)


@bot.command(name='монстр')
async def spawn_monster(ctx, level: int):
    global monster_created
    global monster_health
    global monster_level
    global monster_created_time

    # Проверяем, есть ли роль "admin"
    if not any(role.name == 'admin' for role in ctx.author.roles):
        await ctx.send('Только администраторы могут создавать монстров.')
        return

    # Проверяем, был ли уже создан монстр
    if monster_created:
        await ctx.send('Монстр уже был создан. Подождите, пока он исчезнет.')
        return

    # Создаем нового монстра
    monster_created = True
    monster_health = level * 1000
    monster_level = level
    monster_created_time = datetime.now()
    await ctx.send(f'Монстр уровня {level} создан. Монстр изчезнет через 2 часа!')

    # Ждем 5 секунд и убираем монстра
    await asyncio.sleep(7200)
    reset_monster()
    await ctx.send('Монстр исчез.')

user_levels = {}
@bot.command(name='лвл')
async def check_level(ctx):
    user_level = user_levels.get(ctx.author.id, 0)
    await ctx.author.send(f'{ctx.author.mention}, ваш текущий уровень - {user_level}')



@bot.command(name='атака')
async def attack_monster(ctx):
    if not can_attack_monster(ctx):
        await ctx.send(f'Нельзя атаковать монстра вне канала')
        return

    # Check if the user has attacked too recently
    last_attack_time = last_attack_times.get(ctx.author.id)
    if last_attack_time and (datetime.now() - last_attack_time).seconds < 180:
        await ctx.send(f'{ctx.author.mention}, Вы устали, попробуйте атаковать монстра через {180 - (datetime.now() - last_attack_time).seconds} секунд.')
        return

    # Attack the monster
    damage = random.randint(1, 10)
    user_level = user_levels.get(ctx.author.id, 0)
    damage += user_level * 5  # Добавляем бонус урона в зависимости от уровня игрока
    global monster_health
    monster_health = max(monster_health - damage, 0)
    await ctx.send(f'{ctx.author.mention} атакует монстра и наносит {damage} урона! Осталось {monster_health} единиц здоровья.')
    last_attack_times[ctx.author.id] = datetime.now()

    if monster_health == 0:
        user_levels[ctx.author.id] = user_level + 1
        await ctx.send(f'{ctx.author.mention} победил монстра и получает 1 уровень! Теперь ваш текущий уровень - {user_level + 1}')
        reset_monster()
        
@bot.command()
async def команды(ctx):
    commands_list = []
    for command in bot.commands:
        commands_list.append(command.name)
    commands_str = "\n".join(commands_list)
    await ctx.send(f"Доступные команды:\n```{commands_str}```")

required_role = 'Ивентер'  # Replace with the actual role name

import asyncio

@bot.command()
async def удалить_сообщения(ctx, количество: int):
    """Удаляет указанное количество сообщений в текущем канале"""
    await ctx.channel.purge(limit=количество+1)
    await ctx.send(f"Удалено {количество} сообщений.")


@bot.command()
@commands.has_role(required_role)
async def ивент(ctx, *, event_description):
    announcement_message = f'🎉 **Внимание! Идет проведение ивента!** 🎉\n\n{event_description}'

    # Список исключаемых идентификаторов каналов
    excluded_channel_ids = [1094989671852941363, 1095489835256512592, 1094988929175932979]  # Замените на фактические исключаемые идентификаторы каналов

    # Уведомление всех текстовых каналов о событии, кроме исключенных каналов
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.id not in excluded_channel_ids:
                await channel.send(announcement_message)

    await asyncio.sleep(5)  # Подождать 5 секунд (15 минут в вашем оригинальном коде это 15*60 = 900 секунд)
    
    # Удаление сообщения бота и сообщения пользователя-команды
    await ctx.message.delete()
    await ctx.send("🎉 Ивент успешно запущен! 🎉", delete_after=10)  # Отправить сообщение об успешном запуске ивента, которое автоматически удалится через 10 секунд

@ивент.error
async def ивент_error(ctx, error):
    if isinstance(error, commands.MissingRole):
        user = ctx.author
        message = 'У вас нет доступа для использования этой команды.'

        await user.send(message)

@bot.command(name='изменить_баксы')
async def изменить_баксы(ctx, user: discord.Member, amount: int):
    if not ctx.guild:
        await ctx.send("Команду `изменить_баксы` можно использовать только на сервере.")
        return

    # Проверяем, что указано положительное значение amount
    if amount <= 0:
        await ctx.send("Количество баксов должно быть положительным числом.")
        return

    # Обновляем баланс пользователя в базе данных
    user_id = str(user.id)
    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET bucks = bucks + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

    # Создаем красивое встроенное сообщение (embed) с информацией об изменении баланса
    embed = discord.Embed(
        title="Изменение баланса",
        description=f"Баланс пользователя {user.display_name} успешно изменен на {amount} баксов.",
        color=0x00FF00  # Зеленый цвет
    )
    embed.set_thumbnail(url=user.avatar_url)
    embed.set_footer(text=f"Изменение выполнено администратором {ctx.author.display_name}")

    await ctx.send(embed=embed)

@bot.command()
async def купить_вип(ctx):
    user_id = str(ctx.author.id)

    # Проверяем, был ли уже совершен покупка VIP статуса
    cursor.execute('SELECT * FROM vip_purchases WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result is not None:
        embed = discord.Embed(
            title="Ошибка",
            description="Вы уже приобрели VIP статус.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    # Проверяем, есть ли у пользователя достаточно баксов
    cursor.execute('SELECT bucks FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result is None or result[0] < 50:
        embed = discord.Embed(
            title="Ошибка",
            description="У вас недостаточно баксов для покупки VIP.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return

    # Вычитаем стоимость VIP из баксов пользователя
    cursor.execute('UPDATE users SET bucks = bucks - 50 WHERE user_id = ?', (user_id,))
    conn.commit()

    # Добавляем роль VIP участнику
    vip_role = discord.utils.get(ctx.guild.roles, name="VIP")
    if vip_role is None:
        vip_role = await ctx.guild.create_role(name="VIP", color=discord.Color.purple())
    await ctx.author.add_roles(vip_role)

    # Записываем информацию о покупке VIP статуса
    cursor.execute('INSERT INTO vip_purchases (user_id, purchased_at) VALUES (?, ?)', (user_id, datetime.now()))
    conn.commit()

    embed = discord.Embed(
        title="Успех",
        description="Вы успешно приобрели VIP статус.",
        color=discord.Color.purple()
    )
    await ctx.send(embed=embed)

@bot.command()
async def магазин_вип_рыбак(ctx):
    roles = {
        "Любитель рыбак (50% шанс поймать рыбу)": 4000,
        "Мастер рыбак (60% шанс поймать рыбу)": 7000,
        "Профессионал рыбак (80% шанс поймать рыбу)": 10000
    }

    allowed_channel_id = 1107237345746505789  # Замените на ID вашего текстового канала

    if ctx.channel.id != allowed_channel_id:
        embed = discord.Embed(
            title="Ошибка",
            description="Команда `!магазин_вип_рыбак` может быть использована только в определенном канале.",
            color=discord.Color.red()
        )
        error_message = await ctx.send(embed=embed)
        await error_message.delete(delay=30)  # Удаление сообщения бота через минуту
        return

    embed = discord.Embed(title="Магазин VIP ролей для рыбаков", color=discord.Color.purple())

    for role_name, price in roles.items():
        embed.add_field(name=role_name, value=f"Цена: {price} прусов🪙", inline=False)

    await ctx.send(embed=embed)
    await ctx.message.delete(delay=30)  # Удаление сообщения бота через минуту

@bot.command()
async def магазин_вип_шахтёр(ctx):
    roles = {
        "Мастер шахтёр (50000 прусов)": (50000, "прусов🪙(Добыча прусов от 120 до 300)"),
        "Профессионал шахтёр (100 баксов)": (100, "баксов (Добыча прусов от 400 до 700)")
    }

    allowed_channel_id = 1107237345746505789  # Замените на ID вашего текстового канала

    if ctx.channel.id != allowed_channel_id:
        embed = discord.Embed(
            title="Ошибка",
            description="Команда `!магазин_вип_шахтёр` может быть использована только в определенном канале.",
            color=discord.Color.red()
        )
        error_message = await ctx.send(embed=embed)
        await error_message.delete(delay=30)  # Удаление сообщения бота через 30 секунд
        return

    embed = discord.Embed(title="Магазин VIP ролей для шахтёров", color=discord.Color.purple())

    for role_name, (price, unit) in roles.items():
        embed.add_field(name=role_name, value=f"Цена: {price} {unit}", inline=False)

    await ctx.send(embed=embed)
    await ctx.message.delete(delay=30)  # Удаление сообщения бота через 30 секунд


@bot.command()
async def купить_роль_рыбак(ctx, *, role_name):
    allowed_channel_id = 1107237345746505789  # Замените на ID разрешенного канала
    if ctx.channel.id != allowed_channel_id:
        embed = discord.Embed(
            title="Ошибка",
            description="Эта команда может быть использована только в определенном канале.",
            color=discord.Color.red()
        )
        error_message = await ctx.send(embed=embed)
        await error_message.delete(delay=30)  # Удаление сообщения бота через 30 секунд
        return
    user_id = str(ctx.author.id)
    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user_data = cursor.fetchone()
    if user_data is None:
        cursor.execute("INSERT INTO users (user_id, balance, level, inventory, xp, bucks) VALUES (?, ?, ?, ?, ?, ?)", (user_id, 0, 1, '', 0, 0))
        conn.commit()
        balance = 0
        bucks = 0
    else:
        balance = user_data[1]
        bucks = user_data[5]

    roles = {
        "Любитель рыбак": 4000,
        "Мастер рыбак": 7000,
        "Профессионал рыбак": 10000
    }

    if role_name not in roles:
        embed = discord.Embed(
            title="Ошибка",
            description="Указанная роль не существует в магазине.",
            color=discord.Color.red()
        )
        error_message = await ctx.send(embed=embed)
        await error_message.delete(delay=30)  # Удаление сообщения бота через 30 секунд
        conn.close()
        return

    price = roles[role_name]
    if balance < price:
        embed = discord.Embed(
            title="Ошибка",
            description="У вас недостаточно прусов для покупки этой роли.",
            color=discord.Color.red()
        )
        error_message = await ctx.send(embed=embed)
        await error_message.delete(delay=30)  # Удаление сообщения бота через 30 секунд
        conn.close()
        return

    # Проверяем, имеет ли пользователь уже эту роль
    role = discord.utils.get(ctx.guild.roles, name=role_name)
    if role in ctx.author.roles:
        embed = discord.Embed(
            title="Ошибка",
            description="У вас уже есть эта роль.",
            color=discord.Color.red()
        )
        error_message = await ctx.send(embed=embed)
        await error_message.delete(delay=30)  # Удаление сообщения бота через 30 секунд
        conn.close()
        return

    # Удаляем предыдущую роль пользователя, если есть
    for old_role in ctx.author.roles:
        if old_role.name in roles:
            await ctx.author.remove_roles(old_role)

    # Выдаем роль пользователю
    try:
        await ctx.author.add_roles(role)
    except discord.Forbidden:
        embed = discord.Embed(
            title="Ошибка",
            description="Не удалось выдать роль. Убедитесь, что бот имеет достаточные права.",
            color=discord.Color.red()
        )
        error_message = await ctx.send(embed=embed)
        await error_message.delete(delay=30)  # Удаление сообщения бота через 30 секунд

    # Обновляем баланс пользователя
    new_balance = balance - price
    cursor.execute("UPDATE users SET balance=? WHERE user_id=?", (new_balance, user_id))
    conn.commit()
    conn.close()

    embed = discord.Embed(
        title="Покупка роли",
        description=f"Вы успешно приобрели роль **{role_name}** за {price} прусов.",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)

    embed_dm = discord.Embed(
        title="Покупка роли",
        description=f"Вы успешно приобрели роль **{role_name}** за {price} прусов.",
        color=discord.Color.green()
    )
    await ctx.author.send(embed=embed_dm)

@bot.command()
async def роль_шахта(ctx):
    view = ShaftRoleView()
    await ctx.send("Выберите роль шахтёра:", view=view)

class ShaftRoleView(View):
    def __init__(self):
        super().__init__()

        # Create buttons
        self.create_buttons()

    def create_buttons(self):
        # Create button for "Мастер шахтёр"
        master_button = Button(style=discord.ButtonStyle.primary, label="Мастер шахтёр (50000 прусов)", custom_id="master")
        master_button.callback = self.button_callback
        master_button.style = discord.ButtonStyle.primary
        master_button.style.color = discord.Color.purple()  # Set the button color to purple
        self.add_item(master_button)

        # Create button for "Профессионал шахтёр"
        professional_button = Button(style=discord.ButtonStyle.primary, label="Профессионал шахтёр (100 баксов)", custom_id="professional")
        professional_button.callback = self.button_callback
        professional_button.style = discord.ButtonStyle.primary
        professional_button.style.color = discord.Color.purple()  # Set the button color to purple
        self.add_item(professional_button)

    async def button_callback(self, interaction: discord.Interaction):
        if interaction.data['custom_id'] == "master":
            role_id = 1107284893421019217  # Replace with the actual role ID for "Мастер шахтёр"
            price = 50000  # Price for "Мастер шахтёр"
            currency = "прусы"  # Currency name for "Мастер шахтёр"
        elif interaction.data['custom_id'] == "professional":
            role_id = 1107284997708206220  # Replace with the actual role ID for "Профессионал шахтёр"
            price = 100  # Price for "Профессионал шахтёр"
            currency = "баксы"  # Currency name for "Профессионал шахтёр"
        else:
            return

        role = discord.utils.get(interaction.guild.roles, id=role_id)
        if role is None:
            await interaction.response.send_message("Роль не найдена.", ephemeral=True)
            return

        member = interaction.guild.get_member(interaction.user.id)
        if member is None:
            await interaction.response.send_message("Участник не найден.", ephemeral=True)
            return

        # Get the user's balance from the database
        user_id = str(interaction.user.id)
        conn = sqlite3.connect('economy.db')
        cursor = conn.cursor()
        cursor.execute("SELECT balance, bucks FROM users WHERE user_id=?", (user_id,))
        result = cursor.fetchone()
        if result is None:
            balance = 0
            bucks = 0
        else:
            balance = result[0]
            bucks = result[1]

        if (balance < price and currency == "прусы") or (bucks < price and currency == "баксы"):
            await interaction.response.send_message(f"У вас недостаточно {currency} для покупки этой роли.", ephemeral=True)
            conn.close()
            return

        # Deduct the price from the user's balance or bucks
        if currency == "прусы":
            new_balance = balance - price
            cursor.execute("UPDATE users SET balance=? WHERE user_id=?", (new_balance, user_id))
        elif currency == "баксы":
            new_bucks = bucks - price
            cursor.execute("UPDATE users SET bucks=? WHERE user_id=?", (new_bucks, user_id))

        conn.commit()

        try:
            await member.add_roles(role)
            await interaction.response.send_message(f"Роль `{role.name}` успешно добавлена.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("У меня нет прав на управление ролями.", ephemeral=True)
        finally:
            conn.close()

class LocationsView(View):
    def __init__(self):
        super().__init__()

        # Create buttons
        self.create_buttons()

    def create_buttons(self):

        # Create button for "лес" (forest)
        forest_button = Button(style=discord.ButtonStyle.primary, label="Лес (40000 прусов)", custom_id="forest")
        forest_button.callback = self.button_callback
        self.add_item(forest_button)

        # Create button for "шахты" (mine)
        mine_button = Button(style=discord.ButtonStyle.primary, label="Шахта (60000 прусов)", custom_id="mine")
        mine_button.callback = self.button_callback
        self.add_item(mine_button)

    async def button_callback(self, interaction: discord.Interaction):
        if interaction.data['custom_id'] == "forest":
            role_name = "Лесоруб"  # Role name for "лес"
            price = 40000  # Price for "лес"
        elif interaction.data['custom_id'] == "mine":
            role_name = "Шахтёр"  # Role name for "шахты"
            price = 60000  # Price for "шахта"
        else:
            return

        role = discord.utils.get(interaction.guild.roles, name=role_name)
        if role is None:
            await interaction.response.send_message("Роль не найдена.", ephemeral=True)
            return

        member = interaction.guild.get_member(interaction.user.id)
        if member is None:
            await interaction.response.send_message("Участник не найден.", ephemeral=True)
            return

        # Get the user's balance from the database
        user_id = str(interaction.user.id)
        conn = sqlite3.connect('economy.db')
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        result = cursor.fetchone()
        if result is None:
            balance = 0
        else:
            balance = result[0]

        if balance < price:
            await interaction.response.send_message("У вас недостаточно прусов для покупки этой локации.", ephemeral=True)
            conn.close()
            return

        # Deduct the price from the user's balance
        new_balance = balance - price
        cursor.execute("UPDATE users SET balance=? WHERE user_id=?", (new_balance, user_id))
        conn.commit()
        conn.close()

        try:
            # Add the role to the user
            await member.add_roles(role)
            await interaction.response.send_message(f"Роль `{role.name}` успешно добавлена. Баланс: {new_balance} прусов", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("У меня нет прав на управление ролями.", ephemeral=True)
        except discord.HTTPException:
            await interaction.response.send_message("Не удалось добавить роль.", ephemeral=True)


@bot.command()
async def локации(ctx):
    if ctx.channel.id != 1114625199963394190:  # Replace YOUR_CHANNEL_ID with the ID of the desired text channel
        return

    while True:
        view = LocationsView()
        message = await ctx.send("Выберите локацию:", view=view)

        await asyncio.sleep(120)  # Sleep for 5 minutes (300 seconds)

        await message.delete()  # Delete the previous message

class TradeView(View):
    def __init__(self, author):
        super().__init__(timeout=120)
        self.author = author
        self.value = None

    async def interaction_check(self, interaction: discord.Interaction):
        return interaction.user == self.author

    @discord.ui.button(label='✅', style=discord.ButtonStyle.success, emoji='✅')
    async def accept_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.value = True
        self.stop()

    @discord.ui.button(label='❌', style=discord.ButtonStyle.danger, emoji='❌')
    async def decline_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.value = False
        self.stop()

@bot.command()
async def трейд(ctx, other_user: discord.Member):
    def check_author(message):
        return message.author == ctx.author

    user_id = str(ctx.author.id)
    other_user_id = str(other_user.id)

    # Получаем баланс пользователя
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    user_balance = cursor.fetchone()[0]

    # Получаем инвентарь пользователя
    cursor.execute("SELECT inventory FROM users WHERE user_id=?", (user_id,))
    user_inventory_str = cursor.fetchone()[0]
    if user_inventory_str:
        try:
            user_inventory = json.loads(user_inventory_str)
        except json.JSONDecodeError:
            user_inventory = {}
    else:
        user_inventory = {}

    # Проверяем наличие предметов и достаточность баланса у пользователя
    if not user_inventory:
        await ctx.send('У вас нет предметов в инвентаре.')
        return
    elif user_balance <= 0:
        await ctx.send('У вас недостаточно средств для трейда.')
        return

    # Отправляем список предметов пользователя в личное сообщение
    inventory_text = "\n".join([f"{item}: {quantity}" for item, quantity in user_inventory.items()])
    await ctx.author.send(f"Выберите предмет для передачи:\n{inventory_text}")

    # Ожидаем сообщение с выбранным предметом
    item_msg = await bot.wait_for('message', check=check_author)
    item = item_msg.content

    # Проверяем наличие выбранного предмета у пользователя
    if item not in user_inventory:
        await ctx.author.send('У вас нет такого предмета в инвентаре.')
        return

    # Запрашиваем количество предмета для передачи
    await ctx.author.send('Введите количество предмета:')
    quantity_msg = await bot.wait_for('message', check=check_author)
    quantity = int(quantity_msg.content)

    # Проверяем наличие достаточного количества выбранного предмета у пользователя
    if user_inventory[item] < quantity:
        await ctx.author.send('У вас недостаточно предметов для передачи.')
        return

    # Запрашиваем стоимость предмета
    await ctx.author.send('Введите стоимость предмета:')
    price_msg = await bot.wait_for('message', check=check_author)
    price = int(price_msg.content)

    # Проверяем, достаточно ли средств у покупателя для трейда
    if price > user_balance:
        await ctx.author.send('У вас недостаточно средств для трейда.')
        return

    # Получаем баланс другого пользователя
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (other_user_id,))
    other_user_balance = cursor.fetchone()
    if other_user_balance is None:
        await ctx.send('Произошла ошибка при получении баланса другого пользователя.')
        return
    other_user_balance = other_user_balance[0]

    # Получаем инвентарь другого пользователя
    cursor.execute("SELECT inventory FROM users WHERE user_id=?", (other_user_id,))
    other_user_inventory_str = cursor.fetchone()[0]
    if other_user_inventory_str:
        try:
            other_user_inventory = json.loads(other_user_inventory_str)
        except json.JSONDecodeError:
            other_user_inventory = {}
    else:
        other_user_inventory = {}

    # Добавляем переданные предметы в инвентарь другого пользователя
    if item in other_user_inventory:
        other_user_inventory[item] += quantity
    else:
        other_user_inventory[item] = quantity

    # Обновляем инвентарь и баланс пользователей в базе данных
    user_inventory[item] -= quantity
    user_balance -= price
    other_user_balance += price

    # Обновляем инвентарь и баланс пользователей в базе данных
    cursor.execute("UPDATE users SET inventory=?, balance=? WHERE user_id=?", (json.dumps(user_inventory), user_balance, user_id))
    cursor.execute("UPDATE users SET inventory=?, balance=? WHERE user_id=?", (json.dumps(other_user_inventory), other_user_balance, other_user_id))
    conn.commit()

    # Создаем приватный канал для трейда
    trade_channel = await ctx.guild.create_text_channel(
        name=f"трейд-{ctx.author.id}-{other_user.id}",
        topic=f"Трейд между {ctx.author.name} и {other_user.name}",
        category=ctx.channel.category
    )

    # Прикрепляем логику кнопок для подтверждения или отклонения трейда
    confirmation_message = await trade_channel.send(f"Согласны ли вы на трейд за {price} средств?\n{other_user.mention}")
    await confirmation_message.add_reaction('✅')
    await confirmation_message.add_reaction('❌')

    # Функция для проверки реакций на сообщение с подтверждением трейда
    def check_reaction(reaction, user):
        return user == other_user and str(reaction.emoji) in ['✅', '❌'] and reaction.message.id == confirmation_message.id

    try:
        # Ожидаем реакцию покупателя
        reaction, user = await bot.wait_for('reaction_add', check=check_reaction, timeout=60)
    except asyncio.TimeoutError:
        await trade_channel.send('Время ожидания подтверждения истекло.')
    else:
        if str(reaction.emoji) == '✅':
            await trade_channel.send('Трейд успешно завершен.')
        else:
            await trade_channel.send('Трейд отклонен.')

    # Удаляем приватный канал
    await asyncio.sleep(60)  # Ожидаем 60 секунд
    await trade_channel.delete()

class MarketButtonView(discord.ui.View):
    def __init__(self):
        super().__init__()

    @discord.ui.button(label='Купить рынок', style=discord.ButtonStyle.primary, custom_id='market_button')
    async def on_market_button_click(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        channel_name = f'рынок и {interaction.user.name}'

        # Проверяем, существует ли уже канал "рынок и ник участника" для пользователя
        existing_channel = discord.utils.get(guild.channels, name=channel_name)
        if existing_channel is not None:
            await interaction.response.send_message("Вы уже купили рынок.", ephemeral=True)
            return

        # Проверяем, имеет ли пользователь роль "Продавец"
        if has_seller_role(interaction.user):
            await interaction.response.send_message("У вас уже есть свой рынок. Вы не можете купить больше одного рынка.", ephemeral=True)
            return

        # Проверяем, хватает ли у пользователя 15000 прусов
        if has_enough_prus(interaction.user, 15000):
            # Вычитаем 15000 прусов из баланса пользователя
            subtract_prus(interaction.user, 15000)

            # Создаем текстовый канал с названием "рынок и ник участника"
            category_id = 1095489665215250622  # Замените на ID категории, где нужно создать канал
            category = discord.utils.get(guild.categories, id=category_id)

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }

            channel = await guild.create_text_channel(channel_name, category=category, overwrites=overwrites)

            # Отправляем сообщение с подтверждением, ценой в прусах и названием канала
            await interaction.response.send_message(
                f"Текстовый канал '{channel_name}' создан. Покупка успешно завершена. Цена: 15000 прусов.", ephemeral=True
            )

            # Добавляем роль "Продавец" пользователю
            await interaction.user.add_roles(get_seller_role(guild))

        else:
            # Если у пользователя недостаточно прусов
            await interaction.response.send_message(
                "У вас недостаточно прусов для покупки текстового канала 'рынок'.", ephemeral=True
            )


@bot.command()
async def рынок(ctx):
    """
    Покупка канала 'рынок' за 15000 прусов.
    """
    # Проверяем, существует ли уже канал "рынок и ник участника" для автора команды
    guild = ctx.guild
    channel = discord.utils.get(guild.channels, name=f'рынок и {ctx.author.name}')
    if channel is not None:
        await ctx.send("Вы уже купили рынок.")
        return

    # Создаем экземпляр класса MarketButtonView и отправляем его как сообщение
    view = MarketButtonView()

    # Создаем Embed с информацией о покупке рынка
    embed = discord.Embed(
        title="Купить рынок",
        description="Хотите купить рынок за 15000 прусов?",
        color=discord.Color.blue()
    )

    # Отправляем сообщение с Embed и кнопкой
    message = await ctx.send(embed=embed, view=view)


def has_seller_role(user):
    # Проверяем, имеет ли пользователь роль "Продавец"
    return any(role.name == "Продавец" for role in user.roles)

def get_seller_role(guild):
    # Получаем роль "Продавец" из сервера
    return discord.utils.get(guild.roles, name="Продавец")

def has_enough_prus(user, amount):
    user_id = str(user.id)
    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()

    # Получаем текущий баланс пользователя
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()

    if result is not None:
        balance = result[0]
        return balance >= amount

    return False

def subtract_prus(user, amount):
    user_id = str(user.id)
    conn = sqlite3.connect('economy.db')
    cursor = conn.cursor()

    # Получаем текущий баланс пользователя
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()

    if result is not None:
        balance = result[0]
        new_balance = balance - amount

        # Обновляем баланс пользователя в базе данных
        cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
        conn.commit()

import json

class CasinoView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.add_item(discord.ui.Button(label='Прокрутить слоты'))

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user == self.ctx.author:
            await self.button_callback(interaction)  # Обработка нажатия кнопки
        else:
            await interaction.response.send_message("Вы не можете взаимодействовать с этой кнопкой.", ephemeral=True)
        return False  # Возвращаем False, чтобы представление остановилось после обработки нажатия

    async def button_callback(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)  # Изменено на interaction.user.id
        cursor.execute("SELECT balance, bucks FROM users WHERE user_id=?", (user_id,))
        result = cursor.fetchone()

        if result:
            balance = result[0]
            bucks = result[1]

            if bucks >= 20:
                bucks -= 20
                chance = random.randint(0, 100)

                if chance <= 5:
                    balance += 10000
                    message = f'Вы выиграли 10000 прусов! Ваш текущий баланс: {balance} прусов.'
                elif chance <= 15:
                    balance += 1000
                    message = f'Вы выиграли 1000 прусов! Ваш текущий баланс: {balance} прусов.'
                elif chance <= 55:
                    balance += 100
                    message = f'Вы выиграли 100 прусов! Ваш текущий баланс: {balance} прусов.'
                elif chance <= 85:
                    balance += 10
                    message = f'Вы выиграли 10 прусов! Ваш текущий баланс: {balance} прусов.'
                else:
                    bucks_chance = random.randint(0, 100)

                    if bucks_chance <= 10:
                        bucks += 100
                        message = f'Вы выиграли 100 баксов! Ваш текущий баланс: {bucks} баксов.'
                    elif bucks_chance <= 11:
                        bucks += 10000
                        message = f'Вы выиграли 10000 баксов! Ваш текущий баланс: {bucks} баксов.'
                    elif bucks_chance <= 61:
                        bucks += 10
                        message = f'Вы выиграли 10 баксов! Ваш текущий баланс: {bucks} баксов.'
                    else:
                        bucks += 50
                        message = f'Вы выиграли 50 баксов! Ваш текущий баланс: {bucks} баксов.'

                cursor.execute("UPDATE users SET balance=?, bucks=? WHERE user_id=?", (balance, bucks, user_id))
                conn.commit()
                await interaction.response.send_message(message, ephemeral=True)
            else:
                message = "У вас недостаточно баксов для игры в казино. Получайте баксов больше, чтобы сыграть!"
                await interaction.response.send_message(message, ephemeral=True)
        else:
            message = "Произошла ошибка при получении информации о вашем балансе."
            await interaction.response.send_message(message, ephemeral=True)

@bot.command()
async def casino(ctx):
    view = CasinoView()
    view.ctx = ctx
    message = await ctx.send("Нажмите кнопку, чтобы прокрутить слоты.", view=view)
    
    while True:
        await asyncio.sleep(240)  # Ожидание 5 секунд

        # Удаление предыдущего сообщения и кнопки
        await message.delete()

        # Создание нового сообщения с кнопкой
        view = CasinoView()
        message = await ctx.send("Нажмите кнопку, чтобы прокрутить слоты.", view=view)

@bot.command()
async def казино_описание(ctx):
    description = (
        "**Добро пожаловать в захватывающий мир казино!** 🎉\n\n"
        "🌟 Откройте для себя огромные возможности и невероятные выигрыши! 🤑\n\n"
        "🎰 Присоединяйтесь к нашим потрясающим слотам и погрузитесь в атмосферу настоящего азарта! 🎲\n\n"
        "💰 Что ждет вас в нашем казино:\n"
        "  - 1% шанс выиграть **10 000 прусов** 🪙\n"
        "  - 10% шанс выиграть **1 000 прусов** 🪙\n"
        "  - 40% шанс выиграть **100 прусов** 🪙\n"
        "  - 30% шанс выиграть **10 прусов** 🪙\n"
        "  - 3% шанс выиграть **100 баксов** 💵\n"
        "  - 0.1% шанс выиграть **10 000 баксов** 💵\n"
        "  - 10% шанс выиграть **10 баксов** 💵\n"
        "  - 5% шанс выиграть **50 баксов** 💵\n\n"
        "🔄 Стоимость одного вращения - **20 баксов** 💵\n\n"
        "🍀 Погрузитесь в мир удачи и испытайте адреналин, который ожидает вас на каждом шагу! 🍀\n\n"
        "🎁 Вас ждут невероятные призы и возможность сорвать самый большой джекпот! 🏆\n\n"
        "**Не упустите свой шанс на успех и славу в нашем казино!** 💫\n"
    )
    
    embed = discord.Embed(title="Мировой Джекпот", description=description, color=discord.Color.gold())
    await ctx.send(embed=embed) 

class EventsView(View):
    def __init__(self, channel_id):
        super().__init__()

        self.channel_id = channel_id
        self.message = None
        self.create_button()

    def create_button(self):
        button = discord.ui.Button(style=discord.ButtonStyle.primary, label="Подать заявку")
        button.callback = self.button_callback
        self.add_item(button)

    async def button_callback(self, interaction: discord.Interaction):
        user = interaction.user
        dm_channel = await user.create_dm()
        await dm_channel.send("Чтобы подать заявку, пожалуйста, ответьте на следующие вопросы:")

        application_questions = [
            "1) Имя",
            "2) Возраст",
            "3) Ссылка на профиль Steam",
            "4) Название игры, в которой вы хотите участвовать"
        ]

        application_answers = []
        for question in application_questions:
            embed = discord.Embed(title="Заявка на ивент", description=question, color=discord.Color.blue())
            await dm_channel.send(embed=embed)

            response = await bot.wait_for("message", check=lambda m: m.author == user and m.channel == dm_channel)
            application_answers.append(response.content)

        application_message = "Пользователь {} подал заявку:\n\n".format(user.mention)
        for question, answer in zip(application_questions, application_answers):
            application_message += "**{}:** {}\n".format(question, answer)

        guild = interaction.guild
        channel = guild.get_channel(self.channel_id)

        if self.message:
            await self.message.delete()  # Удалить предыдущее сообщение с кнопкой

        self.message = await channel.send(application_message, view=self)

        await self.message.add_reaction("✅")  # Реакция на подтверждение
        await self.message.add_reaction("❌")  # Реакция на отклонение

        try:
            reaction, _ = await bot.wait_for("reaction_add", timeout=60.0, check=lambda r, u: u == user and str(r.emoji) in ["✅", "❌"])
        except asyncio.TimeoutError:
            await dm_channel.send("Время ожидания истекло.")
            return

        if str(reaction.emoji) == "✅":
            await dm_channel.send("Ваша заявка принята!")
        elif str(reaction.emoji) == "❌":
            await dm_channel.send("Ваша заявка отклонена.")

@bot.command()
async def events(ctx):
    ALLOWED_CHANNEL_ID = 1114628394341109912  # Замените на ваше значение

    if ctx.channel.id != ALLOWED_CHANNEL_ID:
        return  # Если команда не в разрешенном канале, просто выйдите
    embed = discord.Embed(title="Предстоящие ивенты", description="У нас есть несколько захватывающих ивентов, в которых вы можете участвовать и выиграть прекрасные призы!", color=discord.Color.gold())

    events_data = [
        {
            'name': "CS:GO 1v1 турнир",
            'prize': "15 000 прусов и 50 баксов",
            'description': "Приготовьтесь помериться силами в захватывающем турнире CS:GO 1v1. Большой приз в размере 15 000 прусов и 50 баксов ждет победителя!"
        },
        {
            'name': "Valorant командный турнир",
            'prize': "15 000 прусов и 50 баксов",
            'description': "Соберите свою команду и примите участие в нашем командном турнире по Valorant. Победители получат 15 000 прусов и 50 баксов каждому!"
        },
        {
            'name': "Dota 2 кубок",
            'prize': "20 000 прусов и 80 баксов",
            'description': "Станьте легендами в мире Dota 2, победив в нашем кубке. 20 000 прусов и 50 баксов ждут победителей!"
        }
    ]

    for event in events_data:
        embed.add_field(name=event['name'], value=f"**Приз:** {event['prize']}\n{event['description']}", inline=False)

    embed.set_footer(text="Присоединяйтесь к нашим ивентам и побеждайте!")

    channel_id = 1115280470578569266  # Замените на фактический ID текстового канала, куда должны отправляться заявки
    view = EventsView(channel_id)
    message = await ctx.send(embed=embed, view=view)

    async def delete_message():
        await asyncio.sleep(120)  # Ждать 5 минут
        await message.delete()  # Удалить сообщение с кнопкой
        await asyncio.sleep(0.1)  # Ждать 0.1 секунды
        await events(ctx)  # Создать сообщение повторно

    asyncio.ensure_future(delete_message())  # Запустить асинхронную функцию delete_message()

@bot.command()
async def навигатор(ctx):
    # Получение ссылок на текстовые каналы
    новости_проекта = ctx.guild.get_channel(1114628096612651008)  # Замените на ID канала "Новости проекта"
    ивенты = ctx.guild.get_channel(1114628394341109912)  # Замените на ID канала "Ивенты"
    локации = ctx.guild.get_channel(1114625199963394190)  # Замените на ID канала "Локации"
    кланы = ctx.guild.get_channel(1114625236877463552)  # Замените на ID канала "Кланы"
    свадьбы = ctx.guild.get_channel(1114625224210665585)  # Замените на ID канала "Свадьбы"
    вип_магазин = ctx.guild.get_channel(1114643367859589230)  # Замените на ID канала "VIP-магазин"
    идеи_для_проекта = ctx.guild.get_channel(1114639615681384619)  # Замените на ID канала "Идеи для проекта"
    оффтоп = ctx.guild.get_channel(1114633925688561684)  # Замените на ID канала "Оффтоп"
    отзывы_о_проекте = ctx.guild.get_channel(1114634681346949150)  # Замените на ID канала "Отзывы о проекте"
    sheep_chat = ctx.guild.get_channel(1114820448950161488)  # Замените на ID канала "Sheep Chat"
    nsfw18 = ctx.guild.get_channel(1114820753997709312)  # Замените на ID канала "NSFW18+"
    тикеты = ctx.guild.get_channel(1114630507561488505)  # Замените на ID канала "Тикеты"
    заявление_на_помощника_dev = ctx.guild.get_channel(1114629653630566531)  # Замените на ID канала "Заявление на помощника dev."
    заявление_на_менеджера_discord = ctx.guild.get_channel(1114629825357946990)  # Замените на ID канала "Заявление на менеджера Discord"
    купить_рынок = ctx.guild.get_channel(1114629413473103872)  # Замените на ID канала "Купить рынок"
    море = ctx.guild.get_channel(1114623319921143818)  # Замените на ID канала "Море"
    лес = ctx.guild.get_channel(1114623361130168371)  # Замените на ID канала "Лес"
    шахта = ctx.guild.get_channel(1114623342398414878)  # Замените на ID канала "Шахта"
    ремесло = ctx.guild.get_channel(1114631148597956638)  # Замените на ID канала "Ремесло"
    казино = ctx.guild.get_channel(1114626696025493565)  # Замените на ID канала "Казино"

    # Форматирование текста с использованием ссылок
    message = f'''

-{новости_проекта.mention}
В этом канале мы публикуем последние новости и обновления нашего проекта.

-{ивенты.mention}
Здесь вы можете узнать о предстоящих и прошедших ивентах нашего проекта.

-{локации.mention}
В данном канале представлены описания различных локаций в нашем проекте.

-{кланы.mention}
Обсуждение клановой деятельности и поиск новых союзников для создания кланов.

-{вип_магазин.mention}
Приобретайте эксклюзивные предметы и преимущества в нашем VIP-магазине за 50 баксов.

-{идеи_для_проекта.mention}
Вы можете предлагать свои идеи и улучшения для нашего проекта в этом канале.

-{оффтоп.mention}
Свободное общение на различные темы, не относящиеся к проекту.

-{тикеты.mention}
Здесь вы можете подать жалобы и заявки на различные вопросы и проблемы.

-{заявление_на_помощника_dev.mention}
Отправьте заявление на рассмотрение для получения статуса помощника разработчика.

-{заявление_на_менеджера_discord.mention}
Отправьте заявление на рассмотрение для получения статуса менеджера Discord.

-{купить_рынок.mention}
Приобретайте рынок и начните свой собственный бизнес в нашем проекте.

-{море.mention}
Отправляйтесь в наше виртуальное море и наслаждайтесь плаванием и рыбалкой.

-{лес.mention}
Исследуйте лесные просторы и находите различные ресурсы в этом канале.

-{шахта.mention}
Добывайте ценные ресурсы в шахте и создавайте свои уникальные предметы.

-{казино.mention}
Рискуйте и испытайте удачу в нашем виртуальном казино.

-{отзывы_о_проекте.mention}
Оставьте свой отзыв о нашем проекте и поделитесь своим мнением.
'''

    # Отправка сообщения в канал
    await ctx.send(message)

tickets = []

class Ticket:
    def __init__(self, author, channel):
        self.author = author
        self.channel = channel

class TicketButton(discord.ui.View):
    def __init__(self, timeout=300):
        super().__init__(timeout=timeout)
        self.message = None
        self.create_button = discord.ui.Button(style=discord.ButtonStyle.primary, label="Создать тикет")
        self.create_button.callback = self.create_ticket
        self.add_item(self.create_button)

    async def create_ticket(self, interaction: discord.Interaction):
        if any(ticket.author == interaction.user for ticket in tickets):
            await interaction.response.send_message('У вас уже есть открытый тикет.')
            return

        category = discord.utils.get(interaction.guild.categories, name='Тикеты')
        if category is None:
            category = await interaction.guild.create_category(name='Тикеты')

        ticket_channel = await category.create_text_channel(name=f'Тикет-{interaction.user.id}')
        
        for role in interaction.guild.roles:
            if role.name == 'Администратор':
                await ticket_channel.set_permissions(role, read_messages=True, send_messages=True)
                break

        await ticket_channel.set_permissions(interaction.user, read_messages=True, send_messages=True)

        ticket = Ticket(author=interaction.user, channel=ticket_channel)
        tickets.append(ticket)

        rules_message = f"Привет! Это правила тикетов. Пожалуйста, ознакомьтесь с ними перед созданием тикета.\n\nПравило 1: Будьте вежливы и уважительны.\nПравило 2: Опишите вашу проблему или жалобу максимально подробно. \nПравило 3: Оставляйте контактные данные, если необходимо.: "
        rules_message += f"\n\nВы создаете тикет от имени {interaction.user.mention}."

        admin_role = discord.utils.get(interaction.guild.roles, name='Администратор')
        if admin_role is not None:
            admin_mentions = ' '.join(admin_role.mention for member in admin_role.members)
            rules_message += f"\n\nАдминистраторы: {admin_mentions}"

        await ticket_channel.send(rules_message)
        await ticket_channel.send(content="Если ваш вопрос решен или вы хотите закрыть тикет, нажмите на кнопку ниже:", view=CloseTicketButton(ticket_channel))
    
    async def on_timeout(self):
        if self.message:
            await self.message.delete()
        ticket_button = TicketButton()
        rules_message = "Привет! Это правила тикетов. Пожалуйста, ознакомьтесь с ними перед созданием тикета."
        embed = discord.Embed(description=rules_message)
        embed.set_footer(text="Нажмите кнопку ниже, чтобы создать тикет.")
        msg = await self.message.channel.send(embed=embed, view=ticket_button)
        ticket_button.message = msg

class CloseTicketButton(discord.ui.View):
    def __init__(self, channel, timeout=300):
        super().__init__(timeout=timeout)
        self.message = None
        self.channel = channel
        close_button = discord.ui.Button(style=discord.ButtonStyle.danger, label="Закрыть тикет")
        close_button.callback = self.close_ticket
        self.add_item(close_button)

    async def close_ticket(self, interaction: discord.Interaction):
        ticket = next((ticket for ticket in tickets if ticket.channel.id == self.channel.id), None)
        if ticket is not None:
            tickets.remove(ticket)
            await ticket.channel.delete()
            await interaction.response.send_message('Тикет закрыт.')

    async def on_timeout(self):
        if self.message:
            await self.message.delete()
        close_ticket_view = CloseTicketButton(self.channel)
        message = await self.channel.send(content="Если вы хотите закрыть тикет, пожалуйста, создайте его снова.", view=close_ticket_view)
        close_ticket_view.message = message

@bot.command()
async def тикет(ctx):
    rules_message = "Привет! Это правила тикетов. Пожалуйста, ознакомьтесь с ними перед созданием тикета."
    embed = discord.Embed(description=rules_message)
    embed.set_footer(text="Нажмите кнопку ниже, чтобы создать тикет.")
    
    ticket_button = TicketButton()
    msg = await ctx.send(embed=embed, view=ticket_button)
    
    ticket_button.message = msg

@bot.command()
async def заявка_модер(ctx):
    rules = '''
    **Правила подачи заявки на модератора**

    1. Заявитель должен быть активным участником сервера.

    2. Заявитель должен иметь хорошую репутацию и показывать уважение к другим участникам.

    3. Заявитель должен обладать знаниями и опытом, необходимыми для модерации сервера.

    4. Заявка должна быть оформлена в виде отдельного сообщения с использованием формата, указанного ниже.

    **Формат заявки**

    - Имя: [Введите ваше имя]

    - Возраст: [Введите ваш возраст]

    - Город проживания: [Введите ваш город проживания]

    - Доступное время для модерации чата: [Введите, сколько времени в день вы можете позволить для модерации чата]

    - Были ли нарушения: [Укажите, были ли у вас нарушения правил сервера и если да, опишите их]

    - Почему я хочу стать модератором: [Опишите, почему вы хотите стать модератором на нашем сервере]

    После заполнения всех полей, отправьте сообщение с заявкой в этот канал.
    '''

    embed = discord.Embed(
        title="Заявка на модератора",
        description=rules,
        color=0xFFFFFF  # Цвет эмбеда (здесь: белый)
    )

    await ctx.send(embed=embed)

@bot.command()
async def заявка_разраб(ctx):
    rules = '''
    **Правила подачи заявки на помощника разработчика**

    1. Заявитель должен быть активным участником сервера.

    2. Заявитель должен иметь хорошую репутацию и показывать уважение к другим участникам.

    3. Заявитель должен обладать знаниями и опытом, необходимыми для помощи в разработке проекта.

    4. Заявка должна быть оформлена в виде отдельного сообщения с использованием формата, указанного ниже.

    **Формат заявки**

    - Имя: [Введите ваше имя]

    - Возраст: [Введите ваш возраст]

    - Город проживания: [Введите ваш город проживания]

    - Доступное время для помощи в разработке: [Введите, сколько времени в день вы можете позволить для помощи в разработке]

    - Ваши навыки и опыт в разработке: [Опишите ваши навыки и опыт в разработке]

    - Почему я хочу стать помощником разработчика: [Опишите, почему вы хотите стать помощником разработчика на нашем проекте]

    После заполнения всех полей, отправьте сообщение с заявкой в этот канал.
    '''

    embed = discord.Embed(
        title="Заявка на помощника разработчика",
        description=rules,
        color=0xFFFFFF  # Цвет эмбеда (здесь: белый)
    )

    await ctx.send(embed=embed)

@bot.command()
async def дерево(ctx):
    description = '''
    Добро пожаловать в волшебный лес, где каждое дерево хранит в себе тайны и богатства! Здесь вы можете стать лесорубом-магом и получать прусы за рубку деревьев.

    Погрузитесь в фантастическую атмосферу и начните свое приключение. Вам потребуется всего лишь одно нажатие кнопки, чтобы магический топор моментально рубил дерево и превращал его в прусы.

    С каждым удачным ударом, вы будете ощущать магию, пронизывающую ваше существо. Принимайте вызов и собирайте как можно больше прусов.

    Готовы отправиться в это путешествие и ощутить магию рубки деревьев? Просто нажмите на кнопку ниже и начните зарабатывать прусы!
    '''

    embed = discord.Embed(
        title="Лесная рубка",
        description=description,
        color=0xFFFFFF  # Белый цвет эмбеда
    )

    embed.set_image(url="https://gamerwall.pro/uploads/posts/2022-09/1662076695_1-gamerwall-pro-p-magicheskii-les-pinterest-1.jpg")  # URL изображения леса

    await ctx.send(embed=embed)

@bot.command()
async def пещера(ctx):
    description = '''
    Добро пожаловать в глубины таинственной пещеры! Здесь вас ждут богатства и редкие руды. Сделайте свой выбор из трех руд: металла, угля и золота, и начните копать!

    Просто нажмите на кнопку ниже и ваш персонаж начнет использовать свои магические силы, чтобы разрушать скалы и добывать ценные руды. Чем дольше вы копаете, тем больше руды вы найдете.

    Погрузитесь в атмосферу пещеры, где каждое нажатие кнопки открывает вам новые возможности и уникальные находки. Не упустите шанс обнаружить редкие руды и стать самым богатым исследователем пещеры!

    Готовы отправиться в этот захватывающий подземный мир? Просто нажмите на кнопку ниже и начните зарабывать прусы!
    '''

    embed = discord.Embed(
        title="Пещерная копка",
        description=description,
        color=0xFFFFFF  # Белый цвет эмбеда
    )

    embed.set_image(url="https://static.kulturologia.ru/files/u18046/180468719.jpg")  # URL изображения пещеры

    await ctx.send(embed=embed)

@bot.command()
async def море(ctx):
    description = '''
    Добро пожаловать на берег таинственного моря, где скрываются редкие магические рыбы! Здесь вас ожидает увлекательное рыболовное приключение. Подготовьте свою удочку и отправляйтесь на лов рыбы!

    Нажмите на кнопку ниже, чтобы бросить свою удочку в глубины моря. С каждым удачным забросом вы можете поймать редкую магическую рыбу. Встречайте морскую жемчужину, водяного дракона и сиреневого окуня - уникальные создания, которые обладают магическими свойствами.

    Используйте свои рыболовные навыки, чтобы поймать эти редкие магические рыбы. Каждая успешная ловля будет вознаграждена прусами, которые можно обменять на ценные предметы и снаряжение.

    Готовы отправиться в это увлекательное рыболовное приключение? Просто нажмите на кнопку ниже и начните получать за это прусы!
    '''

    embed = discord.Embed(
        title="Морская рыбалка",
        description=description,
        color=0xFFFFFF  # Белый цвет эмбеда
    )

    embed.set_image(url="https://gamerwall.pro/uploads/posts/2021-12/1639619423_3-gamerwall-pro-p-magicheskoe-more-fentezi-krasivo-oboi-4.jpg")  # URL изображения моря

    await ctx.send(embed=embed)

@bot.command()
async def казиноа(ctx):
    description = '''
    Добро пожаловать в увлекательный мир фэнтезийного казино, где вас ждут невероятные призы и шанс выиграть прусы и баксы!

    В казино вы можете испытать свою удачу и сорвать куш. Просто сделайте ставку в баксах и нажмите на кнопку, чтобы запустить колесо удачи. Ваша цель - выстроить комбинацию из трех символов, чтобы получить выигрыш.

    Колесо удачи насыщено фэнтезийными символами, включая драконов, эльфов, волшебные артефакты и многое другое. Вам придется полагаться на свою удачу и стратегию, чтобы достичь великого выигрыша.

    Каждый выигрыш будет вознагражден прусами и баксами, которые вы можете использовать для приобретения фантастических предметов.

    Готовы сделать свою ставку и испытать свою удачу в фэнтезийном казино? Просто нажмите на кнопку ниже, чтобы начать свою захватывающую игру!
    '''

    embed = discord.Embed(
        title="Фэнтезийное казино",
        description=description,
        color=0xFFFFFF  # Белый цвет эмбеда
    )

    embed.set_image(url="https://n-slovo.com.ua/wp-content/uploads/2022/05/%D0%B3%D0%B5%D0%BC%D0%B1%D0%BB%D1%96%D0%BD%D0%B3.jpg")  # URL изображения казино

    await ctx.send(embed=embed)

@bot.command()
async def станокк(ctx):
    description = '''
    Добро пожаловать в станок, где вы можете создавать волшебные предметы из добываемого металла! Здесь вы сможете превратить обычный металл в ценные артефакты и снаряжение.

    После добычи металла из шахты, вам необходимо его переработать. Воспользуйтесь станком, чтобы превратить сырой металл в уникальные предметы. Вы сможете создать инструменты, доспехи, меч.

    Ваша искусность и мастерство определят качество и уникальность созданных предметов. Используйте свои навыки и творческий подход, чтобы создавать мощное снаряжение, которое поможет вам в приключениях.

    Каждое создание будет вознаграждено прусами и дополнительными бонусами. Используйте свои накопленные прусы, чтобы улучшать станок и расширять возможности создания.

    Готовы приступить к созданию магии из металла? Просто нажмите на кнопку ниже, чтобы запустить станок и превратить добытый металл в уникальные предметы!
    '''

    embed = discord.Embed(
        title="Станок для создания предметов",
        description=description,
        color=0xFFFFFF  # Белый цвет эмбеда
    )

    embed.set_image(url="https://cs11.pikabu.ru/post_img/2020/03/13/11/1584124862158858248.jpg")  # URL изображения станка

    await ctx.send(embed=embed)


class LunaFishingView(View):
    def __init__(self, fish):
        super().__init__()
        self.fish = fish
        self.add_item(discord.ui.Button(label='Рыбачить', style=discord.ButtonStyle.primary, emoji='🎣'))

    async def interaction_check(self, interaction: discord.Interaction):
        return interaction.user == self.ctx.author

    async def on_timeout(self):
        await self.message.edit(view=None)

    @discord.ui.button(label='Рыбачить', style=discord.ButtonStyle.primary, emoji='🎣')
    async def on_button_click(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.data['custom_id'] == 'рыбачить':
            if random.random() < 0.5:  # Шанс поймать рыбу - 50%
                await interaction.response.send_message(f'Поздравляем! Вы поймали рыбу: {self.fish}!', ephemeral=True)
            else:
                await interaction.response.send_message('К сожалению, рыба не клюнула.', ephemeral=True)
            self.stop()

@bot.event
async def on_ready():
    print(f'Бот готов: {bot.user.name}')

@bot.command()
async def луна(ctx):
    guild = ctx.guild
    existing_channel = discord.utils.get(guild.channels, name='Лунная река')
    if existing_channel:
        await ctx.send('Канал "Лунная река" уже существует.')
    else:
        channel = await guild.create_text_channel('Лунная река')
        await ctx.send('Канал "Лунная река" создан.')

        fish = random.choice([
            "Дракорыба", "Вакин", "Шипнорып", "Золотая рыбка", "Жемчужинка",
            "Водноклык", "Лунная Рыба", "Кристарыба", "Рыбокрыл", "Вихревая Рыба"
        ])

        view = LunaFishingView(fish)
        message = await channel.send('Событие "Лунная река" началось! Нажмите на кнопку "Рыбачить", чтобы поймать рыбу.', view=view)
        view.message = message
        view.ctx = ctx

class BuyButton(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.buy_button = discord.ui.Button(style=discord.ButtonStyle.primary, label="Купить гриньетку")
        self.buy_button.callback = self.buy_item
        self.add_item(self.buy_button)

    async def buy_item(self, interaction: discord.Interaction):
        # Действие при покупке
        await interaction.response.send_message('+1000000 к здоровью')

@bot.command()
async def пекарня(ctx):
    embed = discord.Embed(title="Пекарня", description="Выберите товар для покупки.", color=0x3498db)
    view = BuyButton()
    
    await ctx.send(embed=embed, view=view)

# Ваши ссылки на гифки
hug_gifs = [
    "https://usagif.com/wp-content/uploads/gif/anime-hug-38.gif",
    "https://usagif.com/wp-content/uploads/gif/anime-hug-83.gif",
    "https://pa1.aminoapps.com/6757/a11885007f1524f5e9b7f8ed5c77de0aa6895b9b_00.gif"
]

kiss_gifs = [
    "https://kinogud.files.wordpress.com/2021/09/indirect-kiss-noragami.gif",
    "https://99px.ru/sstorage/86/2016/04/image_862104161817297640037.gif",
    "https://i.pinimg.com/originals/99/c4/18/99c41869ba1551575aefd9c8ffc533de.gif"
]

hit_gifs = [
    "https://anime-chan.me/uploads/posts/2015-01/1421109650_bbpe.gif",
    "https://i.gifer.com/B7sk.gif",
    "https://99px.ru/sstorage/56/2014/02/image_562402140444032833099.gif"
]

# ID вашего канала, где будут работать команды
ALLOWED_CHANNEL_I = 1114633925688561684  # замените на реальный ID вашего канала

@bot.command(name='обнять')
async def hug(ctx, user: discord.Member):
    if ctx.channel.id != ALLOWED_CHANNEL_I:
        await ctx.send("Вы не можете использовать эту команду в этом канале.")
        return
    
    await ctx.message.delete()  # Удаляем исходное сообщение

    gif_url = random.choice(hug_gifs)
    
    embed = discord.Embed(color=0xFFD700)  # Жёлтый цвет
    embed.set_image(url=gif_url)
    await ctx.send(f"{ctx.author.mention} обнял(а) {user.mention}!", embed=embed)

@bot.command(name='поцеловать')
async def kiss(ctx, user: discord.Member):
    if ctx.channel.id != ALLOWED_CHANNEL_I:
        await ctx.send("Вы не можете использовать эту команду в этом канале.")
        return
    
    await ctx.message.delete()  # Удаляем исходное сообщение

    gif_url = random.choice(kiss_gifs)
    
    embed = discord.Embed(color=0xFF0000)  # Красный цвет
    embed.set_image(url=gif_url)
    await ctx.send(f"{ctx.author.mention} поцеловал(а) {user.mention}!", embed=embed)

@bot.command(name='ударить')
async def hit(ctx, user: discord.Member):
    if ctx.channel.id != ALLOWED_CHANNEL_I:
        await ctx.send("Вы не можете использовать эту команду в этом канале.")
        return
    
    await ctx.message.delete()  # Удаляем исходное сообщение

    gif_url = random.choice(hit_gifs)
    
    embed = discord.Embed(color=0x0000FF)  # Синий цвет
    embed.set_image(url=gif_url)
    await ctx.send(f"{ctx.author.mention} ударил(а) {user.mention}!", embed=embed)

GIF_REWARD_LIST = [
    "https://media.tenor.com/P-Po0bADSmYAAAAM/money-dizzy.gif",
    "https://media.tenor.com/YvaE5INKypcAAAAM/money-cash.gif",
    "https://media.tenor.com/014k1XjXJ7EAAAAC/anime-money.gif",
    # ... добавьте столько URL-гифок, сколько хотите
]

@bot.command(name='награда')
async def daily_reward(ctx):
    await ctx.message.delete()  # Удаление сообщения пользователя
    
    user_id = str(ctx.author.id)
    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user_data = cursor.fetchone()

    if user_data:
        last_reward_date = user_data[6]
        if last_reward_date == str(datetime.date.today()):
            await ctx.send("Вы уже получили свою ежедневную награду сегодня! Попробуйте снова завтра.")
            return

    # Даем награду
    cursor.execute("UPDATE users SET balance = balance + 500, last_daily_reward = ? WHERE user_id = ?", (str(datetime.date.today()), user_id))
    conn.commit()

    # Выбираем случайный GIF из списка
    chosen_gif = random.choice(GIF_REWARD_LIST)
    
    # Создаем встраиваемое сообщение
    embed = discord.Embed(title="🎉 Ежедневная Награда 🎉", description=f"{ctx.author.mention}, вы получили свою ежедневную награду в 500 прусов!", color=discord.Color.gold())
    embed.set_image(url=chosen_gif)
    embed.set_footer(text="Не забывайте заходить каждый день!")

    await ctx.send(embed=embed)

@bot.command(name='обновление')
async def payment_update_announcement(ctx):
    # Создаем встраиваемое сообщение
    embed = discord.Embed(title="🌟 Обновление Платежей 🌟", color=discord.Color.green())

    embed.add_field(name="💳 Новый опыт платежей!", value="Мы рады представить вам усовершенствованную систему платежей на EvilSheep!", inline=False)
    embed.add_field(name="💎 VIP Платежи", value="Получите VIP статус без проблем и задержек. Быстро, надежно и удобно!", inline=True)
    embed.add_field(name="💰 Баксовые транзакции", value="Пополняйте свой баланс баксов еще проще и быстрее!", inline=True)
    embed.add_field(name="🔐 Максимальная безопасность", value="Теперь вам не требуется опасаться неудачных платежей и других проблем. Все процессы проходят автоматически, благодаря новой системе!", inline=False)
    embed.set_footer(text="С EvilSheep ваши платежи всегда под надежной защитой! Ожидайте еще больше удивительных обновлений!")
  
    await ctx.send(embed=embed)        

@bot.command()
async def инструкция(ctx):
    # Создаем встраиваемое сообщение
    embed = discord.Embed(
        title="Инструкция по покупке локаций",
        description="В нашем сервере вы можете приобрести доступ к различным локациям для заработка прусов. Доступные локации:",
        color=0x3498db  # Синий цвет
    )

    # Добавляем информацию о локации "Лес"
    embed.add_field(
        name="🌲 Лес",
        value="Покупка доступа к лесу дает вам роль лесоруба. Это позволяет вам рубить дерево в локации лес и зарабатывать прусы. Стоимость: 40000 прусов.",
        inline=False
    )

    # Добавляем информацию о локации "Шахта"
    embed.add_field(
        name="⛏ Шахта",
        value="Покупка доступа к шахте дает вам роль шахтёра. Это позволяет вам копать руды в шахте и зарабатывать прусы. Стоимость: 60000 прусов.",
        inline=False
    )

    # Отправляем встраиваемое сообщение пользователю
    await ctx.send(embed=embed)

create_users_table()
bot.run('MTEwOTAzODIzNjg4MzQ5NzAzMA.GwjJRe.LTNjYfqBk4ZIO-xyvrGTm23Lv4J9OaY4JHpdpQ')
