from flask import Flask, render_template, request, jsonify
import threading
import time
import json

# Import your existing group chat manager
# from your_module import GroupChatManager  # Uncomment and adjust this line

app = Flask(__name__)

# Global variable to store chat messages
chat_messages = []
# Create a lock for thread-safe operations
chat_lock = threading.Lock()

class MockGroupChatManager:
    """Mock implementation for testing without the actual backend"""
    def __init__(self):
        self.agent_specs = [
            {"name": "助手", "desc": "一个有帮助的助手"},
            {"name": "专家", "desc": "领域专家"},
            {"name": "思考者", "desc": "深度思考者"}
        ]
        self.group_chat = MockGroupChat()
    
    def generate(self, messages):
        # Mock response orders
        return [
            {"名称": "助手", "发言顺序": 1},
            {"名称": "专家", "发言顺序": 2},
            {"名称": "思考者", "发言顺序": 3}
        ]

class MockGroupChat:
    """Mock implementation of group chat"""
    def __init__(self):
        self.messages = []
        self.agents = [MockAgent("助手"), MockAgent("专家"), MockAgent("思考者")]
    
    def append_message(self, sender, content):
        self.messages.append({"sender": sender, "content": content})
        global chat_messages
        with chat_lock:
            chat_messages.append({"sender": sender, "content": content})
    
    def get_transcript(self):
        return "\n".join([f"「{msg['sender']}」：{msg['content']}" for msg in self.messages])

class MockAgent:
    """Mock implementation of an agent"""
    def __init__(self, name):
        self.name = name
    
    def generate(self, messages):
        # Simulate thinking time
        time.sleep(1)
        return f"这是来自{self.name}的回复。" + ("我可以帮助解决问题。" if self.name == "助手" else 
               "根据我的专业知识..." if self.name == "专家" else 
               "我从不同角度思考这个问题...")

# Initialize the manager (use mock for now)
# Replace this with your actual GroupChatManager
manager = MockGroupChatManager()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/send_message', methods=['POST'])
def send_message():
    data = request.json
    user_input = data.get('message', '')
    
    # Add user message to chat
    with chat_lock:
        chat_messages.append({"sender": "用户", "content": user_input})
    
    # Start a new thread to process agent responses
    thread = threading.Thread(target=process_agent_responses, args=(user_input,))
    thread.start()
    
    return jsonify({"status": "Message received"})

def process_agent_responses(user_input):
    # Add user message to group chat
    manager.group_chat.append_message('用户', user_input)
    
    # Get transcript and generate response orders
    transcript = manager.group_chat.get_transcript()
    manager_prompt = transcript + "\n以上是目前为止的群聊信息。请你按找要求来确定发言顺序。"
    response_orders = manager.generate([{'role': 'user', 'content': manager_prompt}])
    
    # Process each agent's response according to the order
    agent_names = [spec['name'] for spec in manager.agent_specs]
    for order in response_orders:
        name, rank = order['名称'], order['发言顺序']
        agent_idx = agent_names.index(name)
        response_agent = manager.group_chat.agents[agent_idx]
        
        # Get updated transcript for this agent
        transcript = manager.group_chat.get_transcript()
        agent_prompt = transcript + "\n以上是目前为止的群聊信息。请你严格根据你的身份角色，直接开始发言："
        
        # Generate response
        response_message = response_agent.generate([{'role': 'user', 'content': agent_prompt}])
        
        # Add to group chat
        manager.group_chat.append_message(name, response_message)

@app.route('/get_messages', methods=['GET'])
def get_messages():
    # Get the last message id the client has
    last_id = int(request.args.get('last_id', -1))
    
    with chat_lock:
        # Return only new messages
        new_messages = chat_messages[last_id + 1:] if last_id >= 0 else chat_messages
        
        # Convert to list of dicts with id
        messages_with_id = [
            {"id": i + last_id + 1, "sender": msg["sender"], "content": msg["content"]}
            for i, msg in enumerate(new_messages)
        ]
    
    return jsonify(messages_with_id)

if __name__ == '__main__':
    app.run(debug=True)
