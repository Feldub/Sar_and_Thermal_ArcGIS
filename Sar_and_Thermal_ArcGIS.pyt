# Импорт необходимых библиотек
import arcpy
import re

# Создание класса Toolbox (набор инструментов)
class Toolbox(object):
    def __init__(self):
        self.label = "SAR and Thermal Toolbox"
        self.alias = ""
        # Список классов, относящихся к этому Toolbox (инструменты, которые будут в наборе инструментов)
        self.tools = [SAR_and_Thermal]
# Создание класса, который отвечает за инструмент
class SAR_and_Thermal(object):
    def __init__(self):
        self.label = "SAR_and_Thermal"
        self.description = "SAR and Thermal data Combination"
        self.canRunInBackground = True

    # Определение параметров инструмента
    def getParameterInfo(self):
        # Входные радиолокационные снимки
        in_sar_rastrs = arcpy.Parameter(
            displayName="Input SAR Rasters",
            name="in_sar_features",
            datatype="GPValueTable",
            parameterType="Required",
            direction="Input")
        in_sar_rastrs.columns = [['GPRasterLayer', 'SAR_Raster']]

        # Входные тепловые снимки
        in_therm_rastrs = arcpy.Parameter(
            displayName="Input Thermal Rasters",
            name="in_therm_features",
            datatype="GPValueTable",
            parameterType="Required",
            direction="Input")
        in_therm_rastrs.columns = [['GPRasterLayer', 'Thermal_Raster']]

        # Входные полигоны с контурами эталонных участков
        in_polygons = arcpy.Parameter(
            displayName="Input landscape polygons",
            name="in_polygons",
            datatype="GPValueTable",
            parameterType="Required",
            direction="Input")
        in_polygons.columns = [['GPFeatureLayer', 'Polygon'], ['GPString', 'Sar deviation koeff'], ['GPString', 'Temp deviation koeff']]

        # Входной полигон с границей исследуемой территории
        border = arcpy.Parameter(
            displayName="Border",
            name="border",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input")

        # Минимальная площадь итоговых полигонов
        min_area = arcpy.Parameter(
            displayName="Minimum area of final polygons, square meters",
            name="merge_distance",
            datatype="GPDouble",
            parameterType="Required",
            direction="Input")
        min_area.value = 30000

        # Путь до набора данных, в который будут сохранены результаты
        output_feature_path = arcpy.Parameter(
            displayName="Output feature path",
            name="output_feature_path",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output")

        params = [in_sar_rastrs, in_therm_rastrs, in_polygons, border, min_area, output_feature_path]
        return params

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        # Автоматическое добавление значений множителей стандартного отклонения для исходных полигонов
        if parameters[2].value:
            if len(re.findall(r'[^\;\s]+', (parameters[2].valueAsText + ' 1 2;').replace(' #', ''))) % 3 == 0:
                parameters[2].value = (parameters[2].valueAsText + ' 1 2;').replace(' #', '')
        return

    def updateMessages(self, parameters):
        return

    # Исполяемая часть инструмента (алгоритм  совместной обработки данных)
    def execute(self, parameters, messages):
        arcpy.env.overwriteOutput = True

        # Чтение исходных параметров
        in_sar_rastrs = parameters[0].valueAsText
        in_therm_rastsr = parameters[1].valueAsText
        in_polygons = parameters[2].valueAsText
        border = parameters[3].valueAsText
        min_area = int(parameters[4].valueAsText)
        output_feature_path = parameters[5].valueAsText

        # Функция для выделение пути к базе геоданных
        def gdb(path):
            gdb = ''
            for i in range(0, len(path.split('\\')) - 1):
                if i == len(path.split('\\')) - 2:
                    gdb += path.split('\\')[i]
                else:
                    gdb += path.split('\\')[i] + '\\'
            return gdb

        # Функция для получения статистических данных о растре в пределах полигона
        def get_rasters_data (polygon_s, rasters_data, property_type, output_feature_path):
            desc = arcpy.Describe(polygon_s)
            n = 1
            data_dict = {}
            for j in rasters_data.split(';'):
                clip_raster_name = r'{0}\{1}_{2}'.format(gdb(output_feature_path), polygon_s.split('\\')[-1], n)

                # Обрезка растра по границам полигона
                arcpy.management.Clip(j, '{0} {1} {2} {3}'.format(desc.extent.XMin, desc.extent.YMin, desc.extent.XMax, desc.extent.YMax),
                                      clip_raster_name, polygon_s, '#', 'ClippingGeometry')

                # Запись необходимых статистических  данных в словарь
                data_dict['{0}_{1}'.format(polygon_s.split('\\')[-1], n)] = float(
                    arcpy.GetRasterProperties_management(clip_raster_name, property_type).getOutput(0).replace(',', '.'))

                # Удаление растра
                arcpy.Delete_management(clip_raster_name)

                n += 1

            return data_dict

        # Функция для получения границ классов в корректном  виде (на основе статистических данных и исходных параметров)
        def reclassify_values(border, polygon_s, number_of_raster, data_dict, min_value, max_value, deviation_dict, deviation_koeff):
            dict_data_and_dev_key = '{0}_{1}'.format(polygon_s.split('\\')[-1], number_of_raster)
            min_max_data_key = '{0}_{1}'.format(border.split('\\')[-1], number_of_raster)
            reclass_value = '{0} {1} 0;{1} {2} 1;{2} {3} 0'.format(min_value[min_max_data_key],
                                                                   str(data_dict[dict_data_and_dev_key] - deviation_dict[dict_data_and_dev_key] *
                                                                       float(deviation_koeff.replace(',', '.'))),
                                                                   str(data_dict[dict_data_and_dev_key] + deviation_dict[dict_data_and_dev_key] *
                                                                       float(deviation_koeff.replace(',', '.'))),
                                                                   max_value[min_max_data_key])

            return reclass_value

        # Удаление старых данных
        for i in re.findall(r'[^\;\s]+', in_polygons)[0::3]:
            for j in range(len(in_sar_rastrs.split(';'))):
                arcpy.Delete_management(
                    r'{0}\{1}_{2}'.format(gdb(output_feature_path), i.split('\\')[-1], j + 1))

        arcpy.management.CreateFeatureDataset(gdb(output_feature_path), output_feature_path.split('\\')[-1])

        # Получение статистики по входным растрам (максимальных и минимальных значений)
        max_sar_dict = get_rasters_data(border, in_sar_rastrs, 'MAXIMUM', output_feature_path)
        min_sar_dict = get_rasters_data(border, in_sar_rastrs, 'MINIMUM', output_feature_path)
        max_thermal_dict = get_rasters_data(border, in_therm_rastsr, 'MAXIMUM', output_feature_path)
        min_thermal_dict = get_rasters_data(border, in_therm_rastsr, 'MINIMUM', output_feature_path)

        # Получение основных данных о полигоне с границей территории исследования
        desc = arcpy.Describe(border)

        # Реклассификация  исходных растров
        for n, i in enumerate(re.findall(r'[^\;\s]+', in_polygons)[0::3]):
            #Получение статистических данных в пределах исходных полигонов для  каждого из растров
            sar_dict = get_rasters_data(i, in_sar_rastrs, 'MEAN', output_feature_path)
            std_sar_dict = get_rasters_data(i, in_sar_rastrs, 'STD', output_feature_path)
            thermal_dict = get_rasters_data(i, in_therm_rastsr, 'MEAN', output_feature_path)
            std_thermal_dict = get_rasters_data(i, in_therm_rastsr, 'STD', output_feature_path)

            # Реклассификация  радиолокационных снимков
            for j in range(len(in_sar_rastrs.split(';'))):
                # Получение значений для реклассификации
                reclass_value = reclassify_values(border, i, j+1, sar_dict,
                                                  min_sar_dict, max_sar_dict, std_sar_dict,
                                                  re.findall(r'[^\;\s]+', in_polygons)[n*3 + 1])
                # Реклассификация
                out_sar_Reclassify = arcpy.sa.Reclassify(in_sar_rastrs.split(';')[j],
                                                         "VALUE", reclass_value, "NODATA")
                # Обрезка исходных радиолокационных снимков по границе исследуемого участка
                arcpy.management.Clip(out_sar_Reclassify,
                                      '{0} {1} {2} {3}'.format(desc.extent.XMin, desc.extent.YMin, desc.extent.XMax, desc.extent.YMax),
                                      r'{0}\sar_{1}_{2}'.format(gdb(output_feature_path), i.split('\\')[-1], j+1),
                                      border, '#', 'ClippingGeometry')

            # Реклассификация тепловых снимков
            for k in range(len(in_therm_rastsr.split(';'))):
                # Получение значений для раклассификации
                reclass_value = reclassify_values(border, i, k+1, thermal_dict,
                                                  min_thermal_dict, max_thermal_dict, std_thermal_dict,
                                                  re.findall(r'[^\;\s]+', in_polygons)[n*3 + 2])
                # Реклассификация
                out_thermal_Reclassify = arcpy.sa.Reclassify(in_therm_rastsr.split(';')[k],
                                                             "VALUE", reclass_value, "NODATA")
                # Обрезка исходных тепловых снимков по границе исследуемого участка
                arcpy.management.Clip(out_thermal_Reclassify,
                                      '{0} {1} {2} {3}'.format(desc.extent.XMin, desc.extent.YMin, desc.extent.XMax, desc.extent.YMax),
                                      r'{0}\therm_{1}_{2}'.format(gdb(output_feature_path), i.split('\\')[-1], k+1),
                                      border, '#', 'ClippingGeometry')

        #Получение итоговых полигонов (все участки, которые в заданной степени соответствуют полигонам с исходными участками за все даты наблюдения)
        for i in re.findall(r'[^\;\s]+', in_polygons)[0::3]:
            for j in range(len(in_sar_rastrs.split(';'))):
                #Взвешенный оверлей по результатам классификации тепловых и радиолокационных  снимков на смежные даты
                Weig_over = arcpy.sa.WeightedOverlay(arcpy.sa.WOTable([
                    [r'{0}\therm_{1}_{2}'.format(gdb(output_feature_path), i.split('\\')[-1], j+1), 50, 'VALUE',
                     arcpy.sa.RemapValue([[0, "Restricted"], [1, 1], ["NODATA", "NODATA"]])],
                    [r'{0}\sar_{1}_{2}'.format(gdb(output_feature_path), i.split('\\')[-1], j+1), 50, 'VALUE',
                     arcpy.sa.RemapValue([[0, "Restricted"], [1, 1], ["NODATA", "NODATA"]])]],
                    [1, 9, 1]))
                #Удаление промежуточных результатов
                arcpy.Delete_management(r'{0}\therm_{1}_{2}'.format(gdb(output_feature_path), i.split('\\')[-1], j+1))
                arcpy.Delete_management(r'{0}\sar_{1}_{2}'.format(gdb(output_feature_path), i.split('\\')[-1], j + 1))
                #Перевод результата взвешенного оверлея в векторный формат
                arcpy.RasterToPolygon_conversion(Weig_over, r'{0}\weight_pol_{1}_{2}'.format(gdb(output_feature_path),
                                                                                             i.split('\\')[-1], j + 1),
                                                 "SIMPLIFY", "VALUE", "SINGLE_OUTER_PART", "")
                #Удаление самого большого полигона (соответствует  границе исследуемой  территории)
                with arcpy.da.UpdateCursor(
                        r'{0}\weight_pol_{1}_{2}'.format(gdb(output_feature_path), i.split('\\')[-1], j+1),
                        ['Shape_Area', 'SHAPE@'], sql_clause =(None, 'ORDER BY Shape_Area DESC')) as cursor:
                    for row in cursor:
                        cursor.deleteRow()
                        break
                    del row

                #Слияние (необходимо для устранения самопересечений
                arcpy.Dissolve_management(
                    r'{0}\weight_pol_{1}_{2}'.format(gdb(output_feature_path), i.split('\\')[-1], j + 1),
                    r'{0}\diss_{1}_{2}'.format(gdb(output_feature_path), i.split('\\')[-1], j + 1),
                    multi_part = 'SINGLE_PART')

                #Удаление промежуточного результата (векторного представления взвешенного оверлея)
                arcpy.Delete_management(
                    r'{0}\weight_pol_{1}_{2}'.format(gdb(output_feature_path), i.split('\\')[-1], j + 1))



            #Получение пересечения для итоговых полигонов (всех участков, которые в заданной степени соответствуют  полигонам с исходными участками за все даты наблюдения)
            arcpy.Intersect_analysis([r'{0}\diss_{1}_{2}'.format(
                gdb(output_feature_path), i.split('\\')[-1], k + 1) for k in range(len(in_sar_rastrs.split(';')))],
                                     r'{0}_{1}_inter'.format(output_feature_path, i.split('\\')[-1]),  "ALL", "", "")

            # Удаление промежуточного результата слияния полигонов
            for diss_data in range(len(in_sar_rastrs.split(';'))):
                arcpy.Delete_management(
                    r'{0}\diss_{1}_{2}'.format(gdb(output_feature_path), i.split('\\')[-1], diss_data + 1))


            # Сохранение только тех полигонов, которые больше заданной в параметрах площади
            arcpy.Select_analysis(
                r'{0}_{1}_inter'.format(output_feature_path, i.split('\\')[-1]),
                r'{0}\{1}_fin'.format(output_feature_path, i.split('\\')[-1]),
                'Shape_Area > {0}'.format(min_area))


            #Удаление промежуточных результатов  (всех участков, которые в заданной степени соответствуют  полигонам с исходными участками за одну из дат) до фильтрации по площади
            arcpy.Delete_management(r'{0}_{1}_inter'.format(output_feature_path, i.split('\\')[-1]))

        return