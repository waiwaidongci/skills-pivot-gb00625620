import {feedback} from '../components/common/fields.js';
import {empty, metrics, panel, pill} from '../components/common/panels.js';
import {table} from '../components/common/table.js';
import {STATUS} from '../constants/enums.js';
import {handler, poll} from '../hooks/action.js';
import {session} from '../stores/session.js';
import {workspace} from '../stores/workspace.js';
import {button, el, h, link, p} from '../utils/dom.js';
import {date, value} from '../utils/format.js';

function limitGroup(config, values) {
  const inputs = config.roster.map(name => el('label', {class:'field inline-field'},
    el('span', {}, name),
    el('input', {name:`${config.key}.${name}`, type:'number', required:true, min:config.min, max:config.max,
      step:'1', value:values[name] ?? 20, inputMode:'numeric'})));
  return el('fieldset', {class:'field-group'}, el('legend', {}, config.label),
    el('div', {class:'limit-grid'}, inputs), config.help && p(config.help, 'subtle'));
}

function readLimits(form, config) {
  const data = new FormData(form);
  const output = {};
  for (const name of config.roster) {
    const raw = data.get(`${config.key}.${name}`);
    const parsed = Number(raw);
    if (!Number.isInteger(parsed) || parsed < config.min || parsed > config.max) {
      throw new Error(`${config.label}「${name}」须为 ${config.min} 至 ${config.max} 的整数`);
    }
    output[name] = parsed;
  }
  return output;
}

function allocationTable(result) {
  const monthLabels = result.months;
  const columns = [
    {key:'channel', label:'招生渠道'}, {key:'program', label:'培训项目'},
    {key:'quota', label:'分配名额（人）'},
    ...monthLabels.map((month, index) => ({
      label:`${month} 转化率`,
      render: row => row.monthly_rates[index].missing_sample
        ? '缺样按零' : value(Number(row.monthly_rates[index].rate_text)),
    })),
  ];
  return table(columns, result.allocation, {caption:'渠道 × 项目名额分配与逐月转化率'});
}

function resultView(job) {
  const result = job.result;
  if (!result) {
    return panel(job.name, pill(STATUS[job.status], job.status), p(job.error || '计算未完成。', 'feedback'));
  }
  const estimateColumns = [
    {key:'month', label:'统计月份'},
    {key:'expected_confirmed', label:'预计确认总人数（人）'},
    {key:'allocated_quota', label:'使用名额总数（人）'},
    {label:'最差月份', render: row => row.is_worst ? pill('最差月份', 'running') : '—'},
  ];
  const evidence = result.rate_evidence.map(group => panel(
    `${group.month} 转化率证据（确认 / 去重受理）`,
    table([
      {key:'channel', label:'招生渠道'}, {key:'program', label:'培训项目'},
      {label:'确认', render: row => row.confirmed},
      {label:'去重受理', render: row => row.intakes},
      {label:'转化率', render: row => row.missing_sample ? '缺样按零'
        : value(Number(row.rate_text))},
    ], group.cells, {caption:`${group.month} 证据表`, pageSize:9})));
  return el('section', {class:'analysis', 'data-testid':'quota-complete'},
    el('div', {class:'result-head'}, p(job.name, 'eyeline'), h(2, result.headline), p(result.note, 'intro-copy'),
      el('div', {class:'actions'}, pill(STATUS[job.status], job.status))),
    metrics(result.metrics),
    panel('逐月预计确认', table(estimateColumns, result.month_estimates,
      {caption:'逐月预计确认总人数'})),
    panel('名额分配方案', allocationTable(result),
      el('div', {class:'two-col'},
        table([{key:'name', label:'招生渠道'}, {key:'cap', label:'接待上限'},
               {key:'used', label:'已分名额'}], result.channel_summary,
          {caption:'渠道接待上限核对', pageSize:9}),
        table([{key:'name', label:'培训项目'}, {key:'need', label:'待补人数'},
               {key:'used', label:'已分名额'}], result.program_summary,
          {caption:'项目待补人数核对', pageSize:9}))),
    ...evidence,
    ...result.sections.map(item => panel(item.title, p(item.text))),
    panel('内部使用提示', p('本页所有分配与估算仅登录后可见，不提供 CSV 导出，也不进入公开复核与交付流程。', 'subtle')));
}

export async function quotaPage(route, refresh) {
  const {spec, datasets, quotaPlans} = workspace;
  if (!session.canWrite) {
    return panel(spec.quota_page, empty('补招名额分析仅向分析员与复核主管开放，只读账号无此页面数据。', '#overview', '返回总览'));
  }
  const error = feedback();

  if (route.id) {
    const job = await workspace.getQuotaPlan(route.id);
    const finished = item => item.status === 'complete' || item.status === 'failed';
    if (!finished(job)) {
      const original = location.hash;
      const status = el('p', {role:'status'}, '后台正在计算补招方案，完成后自动展示。');
      poll(() => workspace.getQuotaPlan(route.id), finished, () => location.hash === original)
        .then(item => { if (item && status.isConnected && location.hash === original) refresh(); })
        .catch(err => { if (status.isConnected) status.textContent = err.message; });
      return panel(job.name, pill(STATUS[job.status], job.status), status,
        button('刷新', {class:'quiet', onClick:refresh}));
    }
    return el('div', {class:'two-col'}, el('div', {class:'wide-panel'}, resultView(job)),
      el('aside', {class:'sidebar-panel'},
        panel('方案来源', link('返回补招分析', '#quota', {class:'quiet'}),
          p(`数据批次 #${job.dataset_id}`, 'filename'), p(date(job.finished_at), 'subtle'),
          el('dl', {class:'dictionary'},
            el('div', {}, el('dt', {}, '渠道接待上限'), el('dd', {}, JSON.stringify(job.channel_caps))),
            el('div', {}, el('dt', {}, '项目待补人数'), el('dd', {}, JSON.stringify(job.program_needs))))),
        panel('计算口径', el('ul', {class:'method-list'}, spec.quota_methodology.map(text => el('li', {}, text))))));
  }

  const submit = button('发起补招名额分析', {type:'submit', class:'primary', 'data-testid':'start-quota'});
  const [capsConfig, needsConfig] = spec.quota_params;
  const form = el('form', {class:'fields', 'data-testid':'quota-form',
    onSubmit: handler(submit, error, async event => {
      const target = event.target;
      const payload = {
        dataset_id: Number(new FormData(target).get('dataset_id')),
        name: new FormData(target).get('name'),
        channel_caps: readLimits(target, capsConfig),
        program_needs: readLimits(target, needsConfig),
      };
      const item = await workspace.startQuota(payload);
      location.hash = `#quota/${item.id}`;
    })},
    el('label', {class:'field'}, el('span', {}, '数据批次'),
      el('select', {name:'dataset_id', required:true},
        datasets.map(item => el('option', {value:item.id}, `${item.name} · ${item.row_count} 行`)))),
    el('label', {class:'field'}, el('span', {}, '方案名称'),
      el('input', {name:'name', type:'text', required:true, maxlength:120,
        value:`样本${spec.quota_page}`})),
    limitGroup(capsConfig, {}), limitGroup(needsConfig, {}),
    el('div', {class:'actions'}, submit), error);

  const planList = table([
    {label:'方案', render: item => link(item.name, `#quota/${item.id}`)},
    {label:'状态', render: item => pill(STATUS[item.status], item.status)},
    {label:'时间', render: item => date(item.created_at)},
    {label:'说明', render: item => item.error ? p(item.error, 'feedback') : '—'},
  ], quotaPlans, {caption:'补招方案记录', empty:'发起后将在此显示，同批次同上限重跑不会新增方案。'});

  return el('div', {class:'two-col'},
    el('div', {class:'wide-panel'},
      panel(spec.quota_page, datasets.length ? form : empty('请先导入受理数据。', '#inputs', '前往导入')),
      panel('方案记录', planList)),
    el('aside', {class:'sidebar-panel'},
      panel('计算口径', el('ul', {class:'method-list'}, spec.quota_methodology.map(text => el('li', {}, text)))),
      panel('并发与续跑', p('同批次同上限的重复提交复用同一方案；后台中断后按发起时保存的批次与上限续跑。', 'subtle'))));
}
