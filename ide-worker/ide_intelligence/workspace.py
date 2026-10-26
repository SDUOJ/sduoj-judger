"""Create fixed single-file projects; never execute submitted source."""

import json


def prepare_project(root, language, name='single-file', shared=False, toolchain=None):
    root.mkdir(parents=True, exist_ok=True)
    if language == 'python':
        (root / 'pyrightconfig.json').write_text(json.dumps({
            'typeCheckingMode': 'basic', 'include': ['main.py'] if shared and not toolchain else ['.'],
            'autoSearchPaths': False,
            **({'pythonVersion': toolchain['pythonVersion'],
                'pythonPlatform': 'Linux'} if toolchain else {}),
        }), encoding='utf-8')
    elif language in {'c', 'cpp'}:
        flags = toolchain['analysisFlags'] if toolchain else ['-std=c++20' if language == 'cpp' else '-std=c17']
        (root / '.clangd').write_text('CompileFlags:\n  Add: ' + json.dumps(flags) + '\n', encoding='utf-8')
    elif language == 'java':
        (root / '.project').write_text(
            '<projectDescription><name>' + name + '</name><buildSpec>'
            '<buildCommand><name>org.eclipse.jdt.core.javabuilder</name>'
            '<arguments/></buildCommand></buildSpec><natures>'
            '<nature>org.eclipse.jdt.core.javanature</nature>'
            '</natures></projectDescription>', encoding='utf-8')
        source = 'src' if shared else ''
        jre = 'org.eclipse.jdt.launching.JRE_CONTAINER'
        if toolchain:
            jre += '/org.eclipse.jdt.internal.debug.ui.launcher.StandardVMType/JavaSE-' + ('1.8' if toolchain['javaVersion'] == '8' else toolchain['javaVersion'])
        (root / '.classpath').write_text(
            '<classpath><classpathentry kind="src" path="' + source + '"/>'
            '<classpathentry kind="con" path="' + jre + '"/>'
            '<classpathentry kind="output" path=".ide-bin"/></classpath>', encoding='utf-8')
        settings = root / '.settings'
        settings.mkdir(exist_ok=True)
        version = toolchain['javaVersion'] if toolchain else '21'
        version = '1.8' if version == '8' else version
        (settings / 'org.eclipse.jdt.core.prefs').write_text(
            'eclipse.preferences.version=1\n' + ''.join(
                'org.eclipse.jdt.core.compiler.' + key + '=' + version + '\n'
                for key in ('compliance', 'source', 'codegen.targetPlatform')), encoding='utf-8')


def prepare_workspace(process):
    process.root.mkdir(parents=True, exist_ok=True)
    if process.document_name is not None or process.language in {'c', 'cpp'}:
        prepare_project(process.root, process.language, toolchain=getattr(process, "toolchain", None))


def prepare(process, code):
    prepare_workspace(process)
    (process.root / process.document_name).write_text(code, encoding='utf-8')


def prepare_document(process, path, code):
    if process.document_name is None:
        project = path.parent.parent if process.language == 'java' else path.parent
        prepare_project(project, process.language, 'ide-' + project.name, shared=True,
                        toolchain=getattr(process, 'toolchain', None))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding='utf-8')
    if process.language in {'c', 'cpp'}:
        profile = getattr(process, 'toolchain', None)
        flags = profile['analysisFlags'] if profile else ['-std=c++20' if process.language == 'cpp' else '-std=c17']
        # clangd does not execute this driver (no --query-driver is enabled).
        driver = 'clang++' if process.language == 'cpp' else 'clang'
        database = [{'directory': str(path.parent), 'file': str(path),
                     'arguments': [driver, *flags, '-fsyntax-only', str(path)]}]
        (path.parent / 'compile_commands.json').write_text(json.dumps(database), encoding='utf-8')
