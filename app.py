from flask import Flask, render_template, request, jsonify
import threading
import time
import json

# Import your existing group chat manager
# from your_module import GroupChatManager  # Uncomment and adjust this line
from group_chat.backend import *


app = Flask(__name__)

# Initialize
ANTHROPIC_API_KEY = "key_here"
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
agents = [ClaudeGroupAgent(client, *spec.values()) for spec in agent_specs[:5]]
group_chat = GroupChat(agents)
manager = ClaudeGroupManager(client, "群管理员", "一个理性公正的群管理员。", group_chat)
# Global variable to store chat messages
chat_messages = []
# Create a lock for thread-safe operations
chat_lock = threading.Lock()

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
