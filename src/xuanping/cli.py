import typer

from xuanping.analysis.bsr_sales import BSRSalesEstimator
from xuanping.config import get_settings
from xuanping.pipeline import Pipeline, export_report, load_calibration_csv
from xuanping.storage import Storage

app = typer.Typer(help="面向亚马逊卖家的免费数据源选品 Agent")


@app.command()
def collect(
    category: str = typer.Option(..., "--category", help="类目 URL 或类目节点 ID"),
    list_type: str = typer.Option("bestsellers", "--type", help="bestsellers、movers 或 new"),
) -> None:
    """采集 Amazon 榜单。"""
    task_id, products = Pipeline().collect(category, list_type)
    typer.echo(f"任务 ID: {task_id}")
    typer.echo(f"采集到 {len(products)} 个商品")
    for product in products:
        typer.echo(f"{product.rank or '-'}\t{product.asin}\t{product.title}")


@app.command()
def analyze(
    category: str = typer.Option(..., "--category", help="类目 URL 或类目节点 ID"),
    top: int = typer.Option(20, "--top", min=1, help="抓取低星评论的 Top N 商品数量"),
    task: str | None = typer.Option(None, "--task", help="接续已有 collect 任务"),
    list_type: str = typer.Option("bestsellers", "--type", help="bestsellers、movers 或 new"),
) -> None:
    """执行完整选品分析流程。"""
    result = Pipeline().run(category, top=top, list_type=list_type, task_id=task)
    typer.echo(f"任务 ID: {result.task_id}")
    typer.echo(f"状态: {result.status}；分析商品: {len(result.products)}")
    for item in result.products[:top]:
        typer.echo(f"{item.product.asin}\t{item.scores.total:.1f}\t{item.product.title}")


@app.command()
def report(
    task: str = typer.Option(..., "--task", help="分析任务 ID"),
    output_format: str = typer.Option("md", "--format", help="md、csv 或 json"),
    output: str | None = typer.Option(None, "--output", help="可选导出文件路径"),
) -> None:
    """导出选品报告。"""
    try:
        content = export_report(
            Storage(get_settings().database_path), task, output_format, output
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    if output:
        typer.echo(f"报告已写入 {output}")
    else:
        typer.echo(content, nl=False)


@app.command()
def calibrate(
    file: str = typer.Option(..., "--file", help="含 bsr、monthly_sales 列的 CSV"),
) -> None:
    """用已知销量样本拟合并持久化类目 BSR 曲线。"""
    category, samples = load_calibration_csv(file)
    estimator = BSRSalesEstimator(Storage(get_settings().database_path))
    a, b = estimator.calibrate(samples, category)
    typer.echo(f"{category}: 月销量 = {a:.3f} * BSR^(-{b:.5f})，样本数 {len(samples)}")


if __name__ == "__main__":
    app()
