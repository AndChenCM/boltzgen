import gradio as gr
import subprocess
import os
import shutil
import uuid
import yaml
import html
from pathlib import Path

# 定义基础工作目录
BASE_WORK_DIR = Path("gradio_workspace")
BASE_WORK_DIR.mkdir(exist_ok=True)

# ==========================================
# 核心功能: 生成带交互功能的 3Dmol.js 页面
# ==========================================
def get_interactive_3dmol_iframe(pdb_path):
    """
    生成一个包含高级交互功能的 3Dmol.js 视图。
    特性：支持鼠标悬停显示残基编号 (Hover Labels)。
    """
    if not pdb_path:
        return ""
        
    try:
        # 1. 读取 PDB 内容
        with open(pdb_path, "r") as f:
            raw_pdb = f.read()
            
        # 2. 清洗数据，确保能嵌入 JS 字符串
        escaped_pdb = raw_pdb.replace("\n", "\\n").replace("'", "\\'")

        # 3. 构造 HTML + JS (核心交互逻辑在这里)
        inner_html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    html, body {{ margin: 0; padding: 0; height: 100%; width: 100%; overflow: hidden; }}
    #viewer {{ width: 100%; height: 100%; position: relative; }}
    /* 简单的 Loading 提示 */
    .loading {{ position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-family: sans-serif; color: #666; }}
  </style>
  <script src="https://3Dmol.org/build/3Dmol-min.js"></script>
</head>
<body>
  <div id="viewer"><div class="loading">正在渲染结构...</div></div>
  <script>
    document.addEventListener("DOMContentLoaded", function() {{
        let element = document.getElementById('viewer');
        let config = {{ backgroundColor: 'white' }};
        let viewer = $3Dmol.createViewer(element, config);
        
        let pdbData = '{escaped_pdb}';
        
        // 加载模型
        viewer.addModel(pdbData, "pdb");
        
        // --- 样式设置 ---
        // 1. 卡通模式 (Cartoon)
        viewer.setStyle({{}}, {{cartoon: {{color: 'spectrum'}}}});
        
        // 2. 同时显示侧链 (Stick) - 可选，为了更清楚看清残基
        // viewer.addStyle({{}}, {{stick: {{radius: 0.1, colorscheme: 'Jmol'}}}});

        // --- 核心交互：鼠标悬停 (Hover) ---
        viewer.setHoverable({{}}, true, 
            function(atom, viewer, event, container) {{
                // 鼠标移入: 添加标签
                if(!atom.label) {{
                    // 构造标签文本: "ResidueName Number" (例如: ALA 15)
                    let labelText = atom.resn + " " + atom.resi;
                    if(atom.chain) labelText += ":" + atom.chain; // 如果有多链，加上链ID
                    
                    atom.label = viewer.addLabel(labelText, {{
                        position: atom, 
                        backgroundColor: 'rgba(0,0,0, 0.7)', // 半透明黑底
                        fontColor: 'white',
                        fontSize: 12,
                        borderRadius: 4,
                        offset: {{x: 0, y: -10}} // 稍微向上偏移
                    }});
                }}
            }},
            function(atom, viewer) {{
                // 鼠标移出: 删除标签
                if(atom.label) {{
                    viewer.removeLabel(atom.label);
                    delete atom.label;
                }}
            }}
        );

        // --- 渲染 ---
        viewer.zoomTo();
        viewer.render();
        
        // 移除 Loading 文字
        let loading = document.querySelector('.loading');
        if(loading) loading.style.display = 'none';
    }});
  </script>
</body>
</html>
"""
        # 4. 封装进 iframe 防止 Gradio 样式干扰
        iframe_html = f"""
        <iframe 
            srcdoc="{html.escape(inner_html)}" 
            width="100%" 
            height="600px" 
            style="border: 1px solid #ddd; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.05);">
        </iframe>
        """
        return iframe_html

    except Exception as e:
        return f"<div style='color:red; padding:20px'>加载失败: {str(e)}</div>"

# ==========================================
# Boltzgen 业务逻辑 (保持不变)
# ==========================================
def generate_config_yaml(work_dir, pdb_path, target_chain_id, binder_len_min, binder_len_max, hotspots_text, is_cyclic):
    binder_entity = {
        "protein": {
            "id": "B",
            "sequence": f"{binder_len_min}..{binder_len_max}"
        }
    }
    if is_cyclic:
        binder_entity["protein"]["cyclic"] = True

    target_entity = {
        "file": {
            "path": str(pdb_path.name),
            "include": [{"chain": {"id": target_chain_id}}]
        }
    }

    if hotspots_text and hotspots_text.strip():
        clean_hotspots = hotspots_text.replace(" ", "")
        target_entity["file"]["binding_types"] = [{
            "chain": {"id": target_chain_id},
            "binding": clean_hotspots
        }]

    config_data = {"entities": [binder_entity, target_entity]}
    yaml_path = work_dir / "design_spec.yaml"
    with open(yaml_path, "w") as f:
        yaml.dump(config_data, f, sort_keys=False)
    return yaml_path

def run_boltzgen_task(input_file, target_chain, binder_min, binder_max, hotspots, is_cyclic, protocol, num_designs, budget, steps):
    job_id = f"run_{str(uuid.uuid4())[:8]}"
    job_dir = BASE_WORK_DIR / job_id
    job_dir.mkdir(exist_ok=True)
    
    if input_file is None:
        return None, "错误：请先上传 PDB 文件"
    
    original_filename = Path(input_file.name).name
    saved_pdb_path = job_dir / original_filename
    shutil.copy(input_file.name, saved_pdb_path)
    
    try:
        yaml_path = generate_config_yaml(
            job_dir, saved_pdb_path, target_chain, binder_min, binder_max, hotspots, is_cyclic
        )
    except Exception as e:
        return None, f"Config Error: {e}"

    cmd = [
        "boltzgen", "run", str(yaml_path.absolute()),
        "--output", str(job_dir.absolute()),
        "--protocol", protocol,
        "--num_designs", str(num_designs),
        "--budget", str(budget),
        "--config", "design", f"sampling.steps={steps}" 
    ]
    
    cmd_str = " ".join(cmd)
    print(f"Executing: {cmd_str}")
    
    try:
        process = subprocess.run(cmd, cwd=str(job_dir), capture_output=True, text=True)
        logs = f"=== CMD ===\n{cmd_str}\n\n=== STDOUT ===\n{process.stdout}\n=== STDERR ===\n{process.stderr}"
    except Exception as e:
        return None, f"System Error: {e}"

    final_dir = job_dir / "final_ranked_designs"
    if not final_dir.exists():
        final_dir = job_dir / "intermediate_designs"
    
    generated_files = list(final_dir.glob("*.pdb")) + list(final_dir.glob("*.cif"))
    
    if not generated_files:
        return None, f"未找到结果文件。\n{logs}"
    
    best_pdb = str(generated_files[0])
    # 返回: (HTML字符串, 日志)
    return get_interactive_3dmol_iframe(best_pdb), logs

# ==========================================
# UI 界面 (换回 HTML 组件)
# ==========================================
with gr.Blocks(title="Boltzgen Web Station") as demo:
    gr.Markdown("## 🧬 Boltzgen 交互式设计平台")
    
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 1. 输入 (Target)")
            pdb_input = gr.File(label="上传 PDB/CIF", file_types=[".pdb", ".cif"])
            target_chain = gr.Textbox(label="Target Chain", value="A")
            hotspots = gr.Textbox(label="Hotspots", placeholder="12,14,61", info="输入残基编号")
            
            gr.Markdown("### 2. 设计 (Binder)")
            with gr.Row():
                binder_min = gr.Number(label="Min Len", value=8)
                binder_max = gr.Number(label="Max Len", value=16)
            is_cyclic = gr.Checkbox(label="环肽 (Cyclic)", value=False)
            
            gr.Markdown("### 3. 参数")
            protocol = gr.Dropdown(["peptide-anything", "protein-anything"], value="peptide-anything", label="Protocol")
            with gr.Accordion("高级参数", open=False):
                num_designs = gr.Number(label="Num Designs", value=2)
                budget = gr.Number(label="Budget", value=1)
                steps = gr.Slider(10, 200, value=50, step=10, label="Steps")
            
            run_btn = gr.Button("🚀 运行", variant="primary")

        with gr.Column(scale=2):
            gr.Markdown("### 3D 结果 (鼠标悬停查看残基)")
            # 这里使用 HTML 组件，并允许渲染 HTML 内容
            output_viewer = gr.HTML(label="3D Viewer")
            log_output = gr.Textbox(label="日志", lines=15)

    # 上传即预览 (调用带 Hover 的生成器)
    pdb_input.change(
        fn=lambda x: get_interactive_3dmol_iframe(x.name) if x else "",
        inputs=pdb_input,
        outputs=output_viewer
    )

    # 运行结果预览 (调用带 Hover 的生成器)
    run_btn.click(
        fn=run_boltzgen_task,
        inputs=[pdb_input, target_chain, binder_min, binder_max, hotspots, is_cyclic, protocol, num_designs, budget, steps],
        outputs=[output_viewer, log_output]
    )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", share=False)