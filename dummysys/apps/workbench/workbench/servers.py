"""本机服务器档案的只读展示投影；认证材料不进入响应。"""
import json


def server_inventory(workspace):
    source = workspace / 'runtime/servers/profiles.json'
    try:
        document = json.loads(source.read_text(encoding='utf-8'))
        profiles = document['profiles']
        if document.get('schema_version') != 1 or not isinstance(profiles, list):
            raise ValueError('unsupported schema')
        rows = []
        for profile in profiles:
            ssh = profile.get('ssh', {})
            model = profile.get('model') or '未登记'
            hardware = profile.get('hardware', {})
            if hardware:
                model = ' / '.join(hardware.get(key) or '待核实'
                                   for key in ('generation', 'product', 'chip'))
            alias = profile['alias']
            password = (f'本机 Profile → {alias} → ssh.password'
                        if ssh.get('password') else '未登记，请向服务器管理员获取')
            verification = profile.get('verification', {})
            reachable = (not hardware.get('reason') and bool(hardware.get('checked_at'))
                         if hardware else verification.get('status') == 'verified')
            rows.append(dict(name=alias, model=model, ip=ssh.get('host', ''),
                generation=hardware.get('generation', '待核实'),
                product=hardware.get('product', model), chip=hardware.get('chip', '待核实'),
                reachable=reachable,
                product_form=hardware.get('product_form', '待核实'),
                host_model=hardware.get('host_model', '待核实'),
                port=ssh.get('port', 22), account=ssh.get('user', ''),
                password_access=password, verified=verification.get('status') == 'verified',
                checked_at=verification.get('checked_at')))
        return dict(available=True, source='runtime/servers/profiles.json', servers=rows)
    except FileNotFoundError:
        return dict(available=True, source='runtime/servers/profiles.json', servers=[])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return dict(available=False, servers=[], message='服务器档案暂不可读，请检查本机 Profile。')
