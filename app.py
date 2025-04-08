from flask import Flask, render_template, request, jsonify, session
import anthropic
import json
import os
from functools import partial
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Initialize the Flask application
app = Flask(__name__)
app.secret_key = os.urandom(24)  # for session management

# Initialize Anthropic client
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    print("WARNING: ANTHROPIC_API_KEY not found in environment variables. Please set it in your .env file.")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# Define the group chat components
class GroupAgent:
    def __init__(self, name, description):
        self.name = name
        self.description = description

    def generate(self, messages):
        pass

    def get_specs(self):
        return {
            "name": self.name,
            "description": self.description,
        }

class ClaudeGroupAgent(GroupAgent):
    def __init__(self, client, name, description, system_prompt, model='claude-3-7-sonnet-20250219', tools=None, thinking=False):
        super().__init__(name, description)
        self.system_prompt = system_prompt
        self.client = client
        self.model = model
        self.thinking = thinking
        self.tools = tools

    def generate(self, messages):
        if self.thinking:
            thinking_message = ""
            response_message = ""

            response = self.client.messages.create(
                model=self.model,
                system=self.system_prompt,
                max_tokens=8096,
                thinking={
                    "type": "enabled",
                    "budget_tokens": 1024
                },
                messages=messages,
            )

            for block in response.content:
                if block.type == 'thinking':
                    thinking_message += block.thinking
                elif block.type == 'text':
                    response_message += block.text

            combined_message = "<think>" + thinking_message + "</think>" + "\n" + response_message
            return combined_message

        elif self.tools:
            response_message = ""
            func_name = None
            func_args = None
            func_return = None
            tool_use_id = None

            tool_response = self.client.messages.create(
                model=self.model,
                system=self.system_prompt,
                max_tokens=8096,
                messages=messages,
                tools=self.tools
            )

            for block in tool_response.content:
                if block.type == 'tool_use':
                    func_name = block.name
                    func_args = block.input
                    tool_use_id = block.id
                    func_return = eval(func_name)(**func_args)

                elif block.type == 'text':
                    response_message += block.text

            if func_name:
                tooled_messages = messages + [
                    {'role': 'assistant',
                     'content': [
                         {
                             "type": "tool_use",
                             "id": tool_use_id,
                             "name": func_name,
                             "input": func_args
                         }
                     ]
                     },
                    {"role": "user",
                     "content": [
                         {
                             "type": "tool_result",
                             "tool_use_id": tool_use_id,
                             "content": f'{func_return}'
                         }
                     ]
                     }]
                second_response = self.client.messages.create(
                    model=self.model,
                    system=self.system_prompt,
                    max_tokens=8096,
                    messages=tooled_messages,
                    tools=self.tools
                )

                response_message += second_response.content[0].text

            return response_message
        else:
            response = self.client.messages.create(
                model=self.model,
                system=self.system_prompt,
                max_tokens=8096,
                messages=messages,
            )
            response_message = response.content[0].text

            return response_message

class ClaudeGroupManager(GroupAgent):
    def __init__(self, client, name, description, group_chat):
        super().__init__(name, description)
        self.group_chat = group_chat
        self.client = client
        self.agent_specs = [agent.get_specs() for agent in group_chat.agents]
        self.agent_specs_str = "\n".join([f"名称：{spec['name']}, 角色：{spec['description']}" for spec in self.agent_specs])

        self.system_prompt = f"""你是一个针对养宠用户创建的群聊的群主兼管理员。群中包含不同的为用户服务的AI宠物助手以及真人兽医。以下是所有群聊内AI助手的信息：
                                {self.agent_specs_str}

                                作为整个群聊的大脑和指挥官，你的职责是根据对话历史和用户输入，判断接下来由哪一些AI助手发言，确定发言顺序。请遵循以下要求：
                                1. 请你根据用户或其他助手的输入，以及每一个AI助手的角色能力，合理地选择进行回答的AI。AI的能力必须能解决当前群聊讨论的问题，或者能够起到辅助性质的作用。
                                2. 在合理的情况下，可以让多个助手发言，以增强群组的讨论度和交互感。
                                4. 注意规避重复性和不必要的发言安排。例如，当提供安慰的助手发言后，应当视情况让他等几轮在发言，又或者，提供额外信息支持的助手应当在有必要向他寻求信息的时候再安排发言，等等。
                                5. 要仔细考虑好发言的顺序安排。例如，如果需要专业问诊助手进行问诊，那么提供信息和情报资讯的助手应当先发言，用于辅助专业问诊助手回答，同时也能让问诊助手在最后直接对用户追问。其他顺序逻辑请你自己多加思考。
                                5. 使用JSON格式输出你的判断。

                                """ \
                             + \
                             """
                                示例JSON输出：
                                <json>[{'名称':'...', '发言顺序':'1'}, {'名称':'...', '发言顺序':'2'}, ...]</json>
                                """

    def generate(self, messages):
        response = self.client.messages.create(
            model="claude-3-7-sonnet-20250219",
            max_tokens=2048,
            system=self.system_prompt,
            messages=messages
        )

        response_message = response.content[0].text
        json_output = eval(response_message[response_message.find("<json>") + 6:response_message.find("</json>")])

        return json_output

class GroupChat:
    def __init__(self, agents, messages=None):
        self.agents = agents
        self.messages = messages if messages else []

    def append_message(self, name, content):
        self.messages.append({'role': name, 'content': content})

    def get_transcript(self):
        transcript = ""
        for message in self.messages:
            transcript += f"{message['role']}: {message['content']}\n"
        return transcript

    def reset(self):
        self.messages = []

# Define tools
def get_collar_data(pet_name, num_days):
    data = {
        "走路时间（小时）": [1.124, 0.801, 1.536, 1.886, 1.934, 1.126, 1.34, 1.324, 1.154, 1.58, 0.349, 1.545, 0.555, 0.699, 1.016, 1.956, 1.036, 0.867, 1.129, 1.104, 0.0, 2.807, 1.22, 1.102, 0.116, 1.599, 0.512, 0.827, 1.249, 1.953, 0.971],
        "睡眠时间（小时）": [1.943, 1.44, 3.553, 1.645, 1.43, 1.872, 1.367, 1.78, 2.378, 4.357, 1.256, 1.797, 1.137, 1.636, 2.253, 0.134, 1.767, 1.854, 2.053, 2.375, 0.025, 3.275, 1.207, 4.455, 0.109, 2.275, 1.057, 1.096, 2.014, 2.49, 2.41],
        "奔跑时间（小时）": [0.005, 0.012, 0.028, 0.024, 0.048, 0.005, 0.095, 0.015, 0.017, 0.035, 0.004, 0.015, 0.005, 0.002, 0.004, 0.007, 0.008, 0.005, 0.016, 0.014, 0.0, 0.011, 0.001, 0.01, 0.009, 0.013, 0.003, 0.001, 0.007, 0.08, 0.037],
        "跳跃时间（小时）": [0.001, 0.006, 0.026, 0.014, 0.016, 0.006, 0.013, 0.019, 0.009, 0.023, 0.003, 0.008, 0.005, 0.003, 0.005, 0.007, 0.009, 0.008, 0.009, 0.017, 0.0, 0.009, 0.003, 0.022, 0.0, 0.004, 0.002, 0.001, 0.013, 0.032, 0.007],
        "进食时间（小时）": [0.169, 0.179, 0.215, 0.276, 0.25, 0.104, 0.107, 0.15, 0.227, 0.243, 0.081, 0.144, 0.063, 0.101, 0.118, 0.283, 0.19, 0.126, 0.2, 0.167, 0.0, 0.19, 0.108, 0.17, 0.01, 0.149, 0.083, 0.082, 0.11, 0.209, 0.207],
        "打滚时间（小时）": [0.001, 0.004, 0.009, 0.005, 0.006, 0.007, 0.002, 0.014, 0.004, 0.011, 0.001, 0.016, 0.004, 0.005, 0.003, 0.003, 0.001, 0.006, 0.007, 0.004, 0.0, 0.003, 0.003, 0.004, 0.0, 0.003, 0.001, 0.003, 0.001, 0.009, 0.004],
        "休息时间（小时）": [3.737, 6.115, 7.193, 5.398, 7.999, 3.133, 6.113, 9.095, 5.344, 6.346, 1.9, 6.577, 3.318, 4.19, 4.997, 10.497, 5.538, 5.783, 5.613, 4.573, 0.001, 7.256, 5.206, 8.303, 0.57, 5.197, 7.117, 4.387, 5.332, 4.571, 10.262],
        "深度睡眠时间（小时）": [13.293, 14.791, 10.634, 14.285, 11.233, 16.746, 12.036, 10.944, 13.892, 6.899, 20.114, 9.863, 6.159, 16.508, 15.121, 8.638, 14.382, 14.44, 13.961, 14.6, 23.97, 9.699, 5.858, 9.199, 23.001, 14.245, 12.217, 17.351, 17.108, 13.891, 9.464],
        "饮食时间（小时）": [0.377, 0.343, 0.423, 0.556, 0.427, 0.244, 0.163, 0.206, 0.471, 0.406, 0.183, 0.226, 0.126, 0.207, 0.235, 0.875, 0.432, 0.238, 0.497, 0.31, 0.0, 0.27, 0.222, 0.347, 0.007, 0.323, 0.105, 0.136, 0.382, 0.273, 0.415],
        "舔舐时间（小时）": [0.552, 0.321, 0.369, 0.221, 0.601, 0.71, 0.164, 0.273, 0.349, 0.212, 0.079, 0.347, 0.14, 0.499, 0.238, 1.45, 0.617, 0.648, 0.399, 0.662, 0.0, 0.286, 0.153, 0.354, 0.004, 0.116, 0.134, 0.055, 0.371, 0.267, 0.213],
        "玩耍时间（小时）": [0.006, 0.009, 0.013, 0.02, 0.018, 0.012, 0.019, 0.012, 0.014, 0.05, 0.002, 0.022, 0.01, 0.004, 0.008, 0.027, 0.013, 0.007, 0.014, 0.014, 0.0, 0.009, 0.005, 0.013, 0.004, 0.006, 0.005, 0.005, 0.005, 0.038, 0.014],
        "抓挠时间（小时）": [0.007, 0.004, 0.003, 0.009, 0.011, 0.009, 0.002, 0.004, 0.01, 0.005, 0.001, 0.012, 0.003, 0.007, 0.002, 0.011, 0.008, 0.002, 0.01, 0.006, 0.0, 0.003, 0.004, 0.005, 0.0, 0.003, 0.002, 0.001, 0.011, 0.008, 0.004]
    }

    return_data = {}
    for k, v in data.items():
        return_data[k] = v[-num_days:]

    return return_data

pet_collar_tools = [
    {
        "name": "get_collar_data",
        "description": "获取智能项圈记录的宠物活动数据，可调整获取的数据天数",
        "input_schema": {
            "type": "object",
            "properties": {
                "pet_name": {
                    "type": "string",
                    "description": "宠物的名字",
                },
                "num_days": {
                    "type": "number",
                    "description": "需要获取的回看数据天数。最大值为30天",
                }
            },
            "required": ["pet_name", "num_days"],
        },
    }
]

group_chat_prompt = "注：你现在处在一个为养宠用户量身定制的群聊当中，群聊中有不同的AI助手和真人为用户进行宠物相关的服务。请你结合群聊历史对话和输入，执行对应的回复，并模拟群聊的聊天模式（如可以使用 @某人 或emoji这样的行为）。"

agent_specs = [{'name': "网络情报专家",
                'description': "一个能够连接互联网的专业的情报搜集专家，可以查看、收集、并总结互联网上的各类资讯，对用户的咨询和其他成员的回答提供帮助。",
                'system_prompt': f"""你是一个能够连接互联网的专业的情报搜集专家，会针对用户的提问或者需求，查看、收集、并总结互联网上的各类资讯，并将搜索内容精确地呈现出来。
                                   {group_chat_prompt}""",
                'model': "claude-3-7-sonnet-20250219", 'tools': None},
               {'name': "智能硬件管家",
                'description': "一个专门负责管理用户家中各种宠物智能设备的管家，能够获取到所有设备记录的宠物各方面行为体征信息，并对这些信息作总结分析，为群聊讨论提供帮助。",
                'system_prompt': f"""一个专门负责管理用户家中各种宠物智能设备的管家，能够获取到所有设备记录的宠物各方面行为体征信息，还能对这些信息作总结分析，并将这些信息和总结提供出来帮助他人。
                                   {group_chat_prompt}""",
                'model': "claude-3-7-sonnet-20250219", 'tools': pet_collar_tools},
               {'name': "专业临床医生",
                'description': "一个经验丰富，专注于专业问诊诊断的临床宠物兽医，可以进行缜密思考并通过多轮反问来帮助确诊宠物疾病。",
                'system_prompt': f"""你是一个经验丰富，专注于专业问诊诊断的临床宠物兽医，可以进行缜密思考并通过多轮反问来帮助确诊宠物疾病。在回答前会进行深度思考。
                                   然后针对用户提出的宠物疾病诊断方面的需求，你会结合历史信息按照如下步骤做出分析：
                                   1. 给出三个最有可能的疾病，并对每一个疾病严密分析，为什么已知症状关联到这三个疾病。
                                   2. 对这三个疾病分别给出概率，总和要为100。
                                   3. 最后判断当前信息是否足够给出诊断。如果不足，则向用户提出1-2个追问问题，继续问诊。如果足够，则给出诊断。

                                   你的问诊输出格式应当如下：
                                   「症状分析」
                                   1. 。。。
                                   2. 。。。
                                   3. 。。。
                                   「疾病关联概率」
                                   1. 。。。
                                   2. 。。。
                                   3. 。。。
                                   此处给出追问问题或诊断结果。

                                   除此之外，对于其他非问诊相关的宠物医疗相关的专业问题，你可以直接给出解答，不需要执行这三个问诊步骤。
                                   {group_chat_prompt}
                                   """,

                'model': "claude-3-7-sonnet-20250219", 'tools': None, 'thinking': True},
               {'name': "温柔体贴小助理",
                'description': "一个温柔的小助理，擅长解决用户的情绪问题，提供各类负面情绪的疏导以及安慰。同时还能对其他成员的回复进行赞赏，捧哏等活跃气氛的行为。",
                'system_prompt': f"""你是一个温柔的小助理，擅长解决用户的情绪问题，提供各类负面情绪的疏导以及安慰。同时还能对其他成员的回复进行赞赏，捧哏等活跃气氛的行为。但是注意！说的话应保持简短。
                                 {group_chat_prompt}""",
                'model': "claude-3-7-sonnet-20250219", 'tools': None},
               {'name': "群聊守护者",
                'description': "一个专门回怼用户不当请求、与宠物完全无关的请求、以及找茬行为的高手。擅长应对某些言语恶劣用户或者不合理的请求。",
                'system_prompt': f"""你是一个专门回怼用户不当请求、与宠物完全无关的请求、以及找茬行为的高手。擅长应对某些言语恶劣用户或者不合理的请求。会用犀利的语言拒绝或回怼用户。
                                   {group_chat_prompt}""",
                'model': "claude-3-7-sonnet-20250219", 'tools': None}
               ]

# Initialize global chat objects
agents = []
group_chat = None
manager = None

# Initialize the agents and group chat
def init_agent_group():
    global agents, group_chat, manager
    
    agents = []
    for spec in agent_specs:
        if spec.get('thinking', False):
            agents.append(ClaudeGroupAgent(client, spec['name'], spec['description'], spec['system_prompt'], 
                                          spec['model'], spec.get('tools', None), thinking=True))
        else:
            agents.append(ClaudeGroupAgent(client, spec['name'], spec['description'], spec['system_prompt'], 
                                          spec['model'], spec.get('tools', None)))
    
    group_chat = GroupChat(agents)
    manager = ClaudeGroupManager(client, "群管理员", "一个理性公正的群管理员。", group_chat)
    return group_chat, manager

# Flask routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/message', methods=['POST'])
def send_message():
    if not group_chat or not manager:
        init_agent_group()
        
    data = request.json
    user_input = data.get('message', '')
    
    # Add user message to chat history
    group_chat.append_message('用户', user_input)
    
    responses = []
    
    # Get manager's decision on who should speak
    transcript = group_chat.get_transcript()
    manager_prompt_template = "\n以上是目前为止的群聊信息。请你按找要求来确定发言顺序。"
    tmp_messages = [{'role': 'user', 'content': transcript + manager_prompt_template}]
    response_orders = manager.generate(tmp_messages)
    
    # Get responses from each agent in order
    agent_names = [agent.name for agent in group_chat.agents]
    for order in response_orders:
        name, rank = order['名称'], order['发言顺序']
        if name in agent_names:
            agent_idx = agent_names.index(name)
            response_agent = group_chat.agents[agent_idx]
            
            transcript = group_chat.get_transcript()
            agent_prompt_template = "\n以上是目前为止的群聊信息。请你严格根据你的身份角色，直接开始发言："
            tmp_messages = [{'role': 'user', 'content': transcript + agent_prompt_template}]
            
            response_message = response_agent.generate(tmp_messages)
            group_chat.append_message(name, response_message)
            
            responses.append({
                'agent': name,
                'message': response_message,
                'description': response_agent.description
            })
    
    return jsonify({
        'status': 'success',
        'responses': responses
    })

@app.route('/api/reset', methods=['POST'])
def reset_chat():
    global group_chat
    if group_chat:
        group_chat.reset()
    return jsonify({'status': 'success', 'message': 'Chat has been reset'})

if __name__ == '__main__':
    init_agent_group()
    app.run(debug=True)
